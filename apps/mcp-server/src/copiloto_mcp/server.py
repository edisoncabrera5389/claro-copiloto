"""Servidor MCP: único punto de acceso del agente a CRM y Facturación.

- Tools de lectura: autónomas, con la PII filtrada.
- Skill evaluarRetencion: reglas de POL-RET-2026 en código.
- Tools de escritura: sin `token_confirmacion` devuelven una PROPUESTA (no ejecutan); con un token
  válido emitido por la API tras la confirmación del asesor, ejecutan el POST una sola vez.
"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from copiloto_mcp import pii
from copiloto_mcp.config import Settings
from copiloto_mcp.confirmacion import Confirmacion, Confirmaciones, ConfirmacionInvalida, huella
from copiloto_mcp.retencion import evaluar_retencion
from copiloto_mcp.sistemas import ClienteSistema, ErrorSistema, SistemaNoDisponible

log = logging.getLogger("copiloto_mcp")

LIMITE_AJUSTE_NIVEL1 = 50_000

INSTRUCCIONES = """\
Herramientas del Copiloto de atención y retención. Reglas:
1. Las tools de lectura y evaluarRetencion se pueden usar libremente.
2. crearTicket, registrarOfertaRetencion y aplicarAjuste tienen efecto. Llámelas SIN token_confirmacion
   para obtener una propuesta; muéstrela al asesor y espere. Solo la API agrega el token cuando el
   asesor confirma en la interfaz. Nunca invente un token.
3. La elegibilidad de retención y las ofertas las decide evaluarRetencion; no ofrezca nada distinto.
4. Los datos personales (documento, celular, correo) no se entregan; no los pida a las tools.
5. Si una tool responde SISTEMA no disponible o CIRCUITO_ABIERTO, informe al asesor y no insista.
"""

ClienteId = Annotated[str, Field(pattern=r"^C-\d{4}$", description="ID del cliente en el CRM, ej. C-1004")]
FacturaId = Annotated[str, Field(pattern=r"^F-\d+$", description="ID de la factura, ej. F-5003")]
Token = Annotated[
    str | None,
    Field(description="Lo agrega la API tras la confirmación del asesor. Omitir para obtener la propuesta."),
]
Categoria = Literal["soporte_tecnico", "facturacion", "consulta_planes", "cancelacion", "portabilidad"]

LECTURA = {"readOnlyHint": True, "openWorldHint": True}
ESCRITURA = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True}


def _pesos(valor: int) -> str:
    return "$" + f"{valor:,}".replace(",", ".")


def _tool_error(e: ErrorSistema) -> ToolError:
    extra = f"sistema={e.sistema}"
    if e.retry_after_s:
        extra += f", reintentar_en_s={e.retry_after_s:.0f}"
    return ToolError(f"{e.codigo}: {e.mensaje} ({extra})")


class RegistroTools(Middleware):
    """Una línea JSON por llamada: tool, resultado y latencia. Nunca los argumentos (pueden tener PII)."""

    async def on_call_tool(self, context, call_next):  # type: ignore[override]
        inicio = time.perf_counter()
        evento: dict[str, Any] = {"tool": context.message.name}
        try:
            resultado = await call_next(context)
            estado = (resultado.structured_content or {}).get("estado") if resultado else None
            evento.update(ok=True, **({"estado": estado} if estado else {}))
            return resultado
        except Exception as e:
            evento.update(ok=False, error=str(e).split(":", 1)[0][:60])
            raise
        finally:
            evento["ms"] = round((time.perf_counter() - inicio) * 1000, 1)
            log.info(json.dumps(evento, ensure_ascii=False))


def crear_servidor(
    settings: Settings | None = None,
    *,
    crm: ClienteSistema | None = None,
    facturacion: ClienteSistema | None = None,
    confirmaciones: Confirmaciones | None = None,
) -> FastMCP:
    s = settings or Settings()
    crm = crm or ClienteSistema("crm", s.crm_url, s)
    fac = facturacion or ClienteSistema("facturacion", s.facturacion_url, s)
    conf = confirmaciones or Confirmaciones(s.confirmacion_secret.get_secret_value(), s.confirmacion_ttl_s)

    mcp = FastMCP("claro-copiloto", instructions=INSTRUCCIONES, version="0.1.0", middleware=[RegistroTools()])

    async def leer(cliente: ClienteSistema, ruta: str, params: dict[str, Any] | None = None) -> Any:
        try:
            return await cliente.get(ruta, params)
        except ErrorSistema as e:
            raise _tool_error(e) from None

    async def accion_confirmada(
        accion: str,
        parametros: dict[str, Any],
        resumen: str,
        token: str | None,
        ejecutar: Callable[[Confirmacion], Awaitable[Any]],
        requiere_rol: str = "asesor",
    ) -> dict[str, Any]:
        if not token:
            return {
                "estado": "requiere_confirmacion",
                "accion": accion,
                "parametros": parametros,
                "huella": huella(accion, parametros),
                "requiere_rol": requiere_rol,
                "resumen": resumen,
                "instruccion": "Muestre esta propuesta al asesor y espere su confirmación en la interfaz. "
                "No vuelva a llamar la tool: la API la ejecutará con el token si el asesor confirma.",
            }
        try:
            c = conf.verificar(token, accion, parametros)
        except ConfirmacionInvalida as e:
            raise ToolError(f"{e.codigo}: {e.mensaje}") from None
        if requiere_rol == "supervisor" and c.rol != "supervisor":
            raise ToolError(
                f"AJUSTE_REQUIERE_APROBACION: ajustes mayores a {_pesos(LIMITE_AJUSTE_NIVEL1)} "
                "requieren la confirmación de un supervisor"
            )
        conf.consumir(c)
        try:
            resultado = await ejecutar(c)
        except ErrorSistema as e:
            if isinstance(e, SistemaNoDisponible) and e.sin_efecto:
                conf.liberar(c)  # no se aplicó: el mismo token sirve para reintentar
            raise _tool_error(e) from None
        return {
            "estado": "ejecutada",
            "accion": accion,
            "confirmada_por": c.asesor_id,
            "rol": c.rol,
            "resultado": resultado,
        }

    # ------------------------------------------------------------------ lectura ---------------

    @mcp.tool(name="buscarCliente", annotations=LECTURA)
    async def buscar_cliente(
        tipo_documento: Literal["CC", "CE", "NIT", "PAS"],
        numero_documento: Annotated[str, Field(min_length=3, max_length=20)],
    ) -> dict[str, Any]:
        """Busca un cliente por documento. Devuelve solo cliente_id, nombre y estado."""
        params = {"tipo_documento": tipo_documento, "numero_documento": numero_documento}
        return pii.filtrar(await leer(crm, "/clientes", params))

    @mcp.tool(name="obtenerCliente", annotations=LECTURA)
    async def obtener_cliente(cliente_id: ClienteId) -> dict[str, Any]:
        """Ficha del cliente: servicios, plan, valor mensual, mora, tickets recientes y ofertas de los
        últimos 12 meses. Sin documento, celular ni correo."""
        return pii.filtrar(await leer(crm, f"/clientes/{cliente_id}"))

    @mcp.tool(name="listarServicios", annotations=LECTURA)
    async def listar_servicios(cliente_id: ClienteId) -> list[dict[str, Any]]:
        """Servicios activos del cliente (plan, valor, fecha de activación, permanencia y equipos)."""
        return pii.filtrar(await leer(crm, f"/clientes/{cliente_id}/servicios"))

    @mcp.tool(name="listarTickets", annotations=LECTURA)
    async def listar_tickets(
        cliente_id: ClienteId,
        dias: Annotated[int, Field(ge=1, le=365, description="Ventana hacia atrás en días")] = 90,
    ) -> list[dict[str, Any]]:
        """Tickets del cliente en la ventana indicada, más recientes primero."""
        return pii.filtrar(await leer(crm, f"/clientes/{cliente_id}/tickets", {"dias": dias}))

    @mcp.tool(name="listarFacturas", annotations=LECTURA)
    async def listar_facturas(
        cliente_id: ClienteId, limite: Annotated[int, Field(ge=1, le=12)] = 3
    ) -> list[dict[str, Any]]:
        """Últimas facturas del cliente (más recientes primero) con detalle de conceptos y estado."""
        return pii.filtrar(await leer(fac, f"/clientes/{cliente_id}/facturas", {"limite": limite}))

    @mcp.tool(name="obtenerSaldo", annotations=LECTURA)
    async def obtener_saldo(cliente_id: ClienteId) -> dict[str, Any]:
        """Saldo pendiente y vencido del cliente y la próxima fecha límite de pago."""
        return pii.filtrar(await leer(fac, f"/clientes/{cliente_id}/saldo"))

    @mcp.tool(name="obtenerFactura", annotations=LECTURA)
    async def obtener_factura(factura_id: FacturaId) -> dict[str, Any]:
        """Detalle de una factura, incluidos los ajustes aplicados."""
        return pii.filtrar(await leer(fac, f"/facturas/{factura_id}"))

    # ------------------------------------------------------------------ skill -----------------

    async def evaluar(cliente_id: str, servicio_id: str | None = None) -> dict[str, Any]:
        ficha_r, tickets_r, facturas_r = await asyncio.gather(
            crm.get(f"/clientes/{cliente_id}"),
            crm.get(f"/clientes/{cliente_id}/tickets", {"dias": 90}),
            fac.get(f"/clientes/{cliente_id}/facturas", {"limite": 1}),
            return_exceptions=True,
        )
        for r in (ficha_r, tickets_r):  # sin ficha o sin tickets no se puede aplicar la política
            if isinstance(r, ErrorSistema):
                raise _tool_error(r)
            if isinstance(r, BaseException):
                raise r
        advertencias = []
        facturas: list[dict[str, Any]] | None = None
        if isinstance(facturas_r, ErrorSistema):
            advertencias.append(
                f"Facturación no respondió ({facturas_r.codigo}): "
                "la Promoción Fibra 500 se verificó solo con el CRM."
            )
        elif isinstance(facturas_r, BaseException):
            raise facturas_r
        else:
            facturas = facturas_r
        if servicio_id and not any(
            sv["servicio_id"] == servicio_id and sv["estado"] == "activo" for sv in ficha_r["servicios"]
        ):
            raise ToolError(f"SERVICIO_NO_ENCONTRADO: {cliente_id} no tiene el servicio activo {servicio_id}")
        resultado = evaluar_retencion(ficha_r, tickets_r, s.fecha_referencia, facturas, servicio_id)
        resultado["advertencias"] = advertencias
        return resultado

    @mcp.tool(name="evaluarRetencion", annotations=LECTURA)
    async def evaluar_retencion_tool(
        cliente_id: ClienteId,
        servicio_id: Annotated[
            str | None, Field(description="Servicio a cancelar; omitir para todos")
        ] = None,
    ) -> dict[str, Any]:
        """Aplica la Política de Retención POL-RET-2026 v3.1: elegibilidad (mora, oferta en 12 meses),
        tramo de antigüedad, ofertas RET-A/RET-B por servicio, visita técnica prioritaria previa,
        Mesa Especializada y restricciones.
        Usar SIEMPRE antes de ofrecer algo a un cliente que quiere cancelar."""
        return await evaluar(cliente_id, servicio_id)

    # ------------------------------------------------------------------ escritura -------------

    @mcp.tool(name="crearTicket", annotations=ESCRITURA)
    async def crear_ticket(
        cliente_id: ClienteId,
        categoria: Categoria,
        descripcion: Annotated[str, Field(min_length=1, max_length=1000)],
        prioridad: Literal["estandar", "prioritaria"] = "estandar",
        escalar_a: Literal["nivel2", "supervisor", "mesa_retencion"] | None = None,
        token_confirmacion: Token = None,
    ) -> dict[str, Any]:
        """Crea un ticket en el CRM (escalamiento, visita técnica, Mesa de Retención). Requiere confirmación.
        Documento, celular y correo se enmascaran en la descripción."""
        parametros = {
            "cliente_id": cliente_id,
            "categoria": categoria,
            "descripcion": pii.redactar_texto(descripcion),
            "prioridad": prioridad,
            "escalar_a": escalar_a,
        }
        resumen = f"Crear ticket de {categoria} con prioridad {prioridad} para {cliente_id}" + (
            f", escalado a {escalar_a}" if escalar_a else ""
        )

        async def ejecutar(_: Confirmacion) -> Any:
            cuerpo = {k: v for k, v in parametros.items() if k != "cliente_id"}
            return await crm.post(f"/clientes/{cliente_id}/tickets", cuerpo)

        return await accion_confirmada("crearTicket", parametros, resumen, token_confirmacion, ejecutar)

    @mcp.tool(name="registrarOfertaRetencion", annotations=ESCRITURA)
    async def registrar_oferta(
        cliente_id: ClienteId,
        codigo: Literal["RET-A", "RET-B"],
        servicio_id: Annotated[str | None, Field(description="Obligatorio si hay varias opciones")] = None,
        token_confirmacion: Token = None,
    ) -> dict[str, Any]:
        """Registra en el CRM la oferta de retención que el cliente aceptó. Requiere confirmación.
        Vuelve a evaluar la política antes de proponer y antes de ejecutar; la descripción sale de la
        política (no se aceptan condiciones redactadas por el agente)."""
        evaluacion = await evaluar(cliente_id)
        if not evaluacion["elegible"]:
            detalle = "; ".join(m["detalle"] for m in evaluacion["motivos_no_elegible"])
            raise ToolError(f"CLIENTE_NO_ELEGIBLE: {detalle}")
        candidatas = [
            (sv, o)
            for sv in evaluacion["servicios"]
            if servicio_id in (None, sv["servicio_id"])
            for o in sv["ofertas"]
            if o["codigo"] == codigo
        ]
        disponibles = [(sv, o) for sv, o in candidatas if o["disponible"]]
        if not disponibles:
            if candidatas:
                raise ToolError(f"OFERTA_NO_DISPONIBLE: {candidatas[0][1]['restriccion']}")
            raise ToolError(f"OFERTA_NO_APLICA: {codigo} no aplica a los servicios indicados de {cliente_id}")
        if len(disponibles) > 1:
            opciones = ", ".join(sv["servicio_id"] for sv, _ in disponibles)
            raise ToolError(f"SERVICIO_REQUERIDO: indique servicio_id ({opciones})")
        sv, oferta = disponibles[0]
        parametros = {
            "cliente_id": cliente_id,
            "codigo": codigo,
            "servicio_id": sv["servicio_id"],
            "descripcion": f"{oferta['descripcion']} [{sv['servicio_id']}]",
        }
        resumen = f"Registrar oferta {codigo} para {cliente_id}: {oferta['descripcion']}"

        async def ejecutar(c: Confirmacion) -> Any:
            cuerpo = {"codigo": codigo, "descripcion": parametros["descripcion"], "asesor_id": c.asesor_id}
            return await crm.post(f"/clientes/{cliente_id}/ofertas-retencion", cuerpo)

        return await accion_confirmada(
            "registrarOfertaRetencion", parametros, resumen, token_confirmacion, ejecutar
        )

    @mcp.tool(name="aplicarAjuste", annotations=ESCRITURA)
    async def aplicar_ajuste(
        factura_id: FacturaId,
        valor: Annotated[int, Field(ge=1, description="Valor en pesos")],
        motivo: Annotated[str, Field(min_length=1, max_length=500)],
        token_confirmacion: Token = None,
    ) -> dict[str, Any]:
        """Aplica un ajuste a una factura. Requiere confirmación; si supera $50.000, la confirmación debe
        ser de un supervisor (queda registrado como aprobado_por)."""
        parametros = {"factura_id": factura_id, "valor": valor, "motivo": pii.redactar_texto(motivo)}
        requiere_rol = "supervisor" if valor > LIMITE_AJUSTE_NIVEL1 else "asesor"
        resumen = f"Aplicar ajuste de {_pesos(valor)} a la factura {factura_id}" + (
            f" (supera {_pesos(LIMITE_AJUSTE_NIVEL1)}: requiere aprobación de supervisor)"
            if requiere_rol == "supervisor"
            else ""
        )

        async def ejecutar(c: Confirmacion) -> Any:
            cuerpo = {
                "valor": valor,
                "motivo": parametros["motivo"],
                "aprobado_por": c.asesor_id if c.rol == "supervisor" else None,
            }
            return await fac.post(f"/facturas/{factura_id}/ajustes", cuerpo)

        return await accion_confirmada(
            "aplicarAjuste", parametros, resumen, token_confirmacion, ejecutar, requiere_rol
        )

    # ------------------------------------------------------------------ operación -------------

    @mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "estado": "ok",
                "servicio": "mcp-server",
                "sistemas": {
                    "crm": {**crm.breaker.resumen(), "reintentos": crm.reintentos_realizados},
                    "facturacion": {**fac.breaker.resumen(), "reintentos": fac.reintentos_realizados},
                },
            }
        )

    return mcp
