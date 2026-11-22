"""Grafo agéntico (LangGraph), SAD 2.3:

    entrada (guardrails) ─► bloqueado ─────────────────────────────► rechazar ─► FIN
          └─► clasificar (intención / alcance) ─► fuera de alcance ─► rechazar
                                               ├─► escalar (política, numeral 2) ─► salida ─► FIN
                                               └─► agente (RAG + tools MCP, ≤ 6 pasos) ─► salida ─► FIN

- Reglas en código: escalamiento, inyección y alcance se deciden antes del LLM.
- El LLM ve la PII como marcadores (<DOCUMENTO_1>); la bóveda restituye el dato solo al llamar la tool.
- Las tools de escritura devuelven propuestas: se guardan y el asesor confirma por la API.
- Salida: citas validadas, confianza calculada y, si es baja, "no encontrado → escalar" (política, numeral 2).
- Eventos de streaming: estado, token, reiniciar, tool, propuesta, fuentes, reemplazar.
"""

import asyncio
import json
import re
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from copiloto_api import prompts
from copiloto_api.config import Settings
from copiloto_api.guardrails import analizar_entrada, validar_citas
from copiloto_api.llm import ClienteLLM, Uso
from copiloto_api.mcp_cliente import ClienteMCP, a_formato_llm
from copiloto_api.ml_cliente import ClienteML
from copiloto_api.observabilidad import nodo
from copiloto_api.pii import Boveda, redactar
from copiloto_api.rag import Fragmento, Retriever

_CLIENTE = re.compile(r"\bC-\d{4}\b", re.IGNORECASE)
_CANCELACION = re.compile(
    r"cancel|retir(ar|o)|dar(se)? de baja|terminar el contrato|irse a otro operador|portar", re.IGNORECASE
)
INTENCIONES = {
    "consulta_planes",
    "facturacion",
    "soporte_tecnico",
    "cancelacion",
    "portabilidad",
    "contratos",
    "otro",
}
CATEGORIA_TICKET = {
    "consulta_planes": "consulta_planes",
    "facturacion": "facturacion",
    "soporte_tecnico": "soporte_tecnico",
    "cancelacion": "cancelacion",
    "portabilidad": "portabilidad",
}

RESPUESTA_BLOQUEO = (
    "No puedo procesar esa instrucción: intenta modificar las reglas del asistente. "
    "Si necesitas ayuda con un cliente, descríbeme el caso."
)
RESPUESTA_FUERA_ALCANCE = (
    "Esa consulta está fuera de alcance: solo puedo ayudarte con temas de atención al cliente "
    "(planes, facturación, soporte técnico, contratos, portabilidad y retención)."
)
RESPUESTA_NO_ENCONTRADO = (
    "No encontré información suficiente en las fuentes oficiales para responder con seguridad. "
    "Según la Política de Escalamiento (numeral 2), escala el caso a un supervisor."
)


def _es_no_encontrado(error: str | None) -> bool:
    """Código de negocio del MCP del tipo CLIENTE_NO_ENCONTRADO / FACTURA_NO_ENCONTRADA (antes de ':')."""
    return bool(error) and "NO_ENCONTRAD" in error.split(":", 1)[0]


BUSCAR_CONOCIMIENTO = {
    "type": "function",
    "function": {
        "name": "buscar_conocimiento",
        "description": "Busca en las fuentes oficiales vigentes (catálogo, contratos, políticas, manuales, "
        "FAQ, comunicados). Devuelve fragmentos numerados [n] para citar.",
        "parameters": {
            "type": "object",
            "properties": {
                "consulta": {
                    "type": "string",
                    "description": "Consulta específica en español, con los términos y códigos exactos "
                    "(ej. 'LOS rojo', 'E-202')",
                }
            },
            "required": ["consulta"],
        },
    },
}


class Estado(TypedDict, total=False):
    # entrada
    sesion_id: str
    usuario: dict[str, str]
    mensaje: str
    historial: list[dict[str, str]]
    # decisiones
    mensaje_llm: str
    boveda: dict[str, str]
    cliente_id: str | None
    ruta: str
    motivo: str | None
    detalle: str | None
    intencion: str
    confianza_intencion: float
    origen_intencion: str  # svm | reglas | llm
    riesgo_churn: dict[str, Any] | None  # señal de priorización (nunca decide la elegibilidad)
    # resultado
    fuentes: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    propuestas: list[dict[str, Any]]
    respuesta: str
    confianza: float
    citadas: list[int]
    sin_cita: bool
    advertencias: list[str]
    modelo: str
    uso: Uso
    precarga: list[Fragmento]


def _formatear_fragmentos(frags: list[tuple[int, Fragmento]]) -> str:
    if not frags:
        return "Sin resultados en las fuentes oficiales vigentes."
    return "\n\n".join(
        f"[{n}] {f.fuente} · v{f.version} · {f.seccion or f.titulo}\n{f.texto}" for n, f in frags
    )


def crear_agente(
    s: Settings,
    llm: ClienteLLM,
    retriever: Retriever,
    mcp: ClienteMCP,
    guardar_propuesta: Callable[[dict[str, Any]], Awaitable[str]],
    ml: ClienteML,
    fecha_referencia: str = "2026-11-18",
) -> Any:
    async def emitir_token(texto: str) -> None:
        get_stream_writer()({"tipo": "token", "texto": texto})  # la API mide el TTFT sobre este evento

    # ------------------------------------------------------------------------- nodos ------

    async def entrada(e: Estado) -> dict[str, Any]:
        get_stream_writer()({"tipo": "estado", "paso": "guardrails"})
        boveda = Boveda()
        a = analizar_entrada(e["mensaje"], boveda)
        cliente_id = a.cliente_id
        if cliente_id is None:  # seguimiento ("¿y su saldo?"): el cliente viene de turnos anteriores
            for m in reversed(e.get("historial", [])):
                if found := _CLIENTE.search(m.get("content", "")):
                    cliente_id = found.group(0).upper()
                    break
        return {
            "ruta": a.ruta,
            "motivo": a.motivo,
            "detalle": a.detalle,
            "mensaje_llm": a.mensaje_llm,
            "cliente_id": cliente_id,
            "boveda": boveda.datos,
            "uso": Uso(),
            "fuentes": [],
            "tools": [],
            "propuestas": [],
            "advertencias": [],
            "precarga": [],
        }

    def intencion_ml(pred: dict[str, Any] | None) -> tuple[str, float, str] | None:
        """Etiqueta del SVM si supera el umbral (SAD 2.7). Bajo el umbral, reglas como respaldo."""
        if pred and pred.get("intencion") in INTENCIONES and pred.get("confianza", 0) >= s.umbral_intencion:
            return pred["intencion"], float(pred["confianza"]), "svm"
        return None

    def intencion_reglas(e: Estado) -> tuple[str, float, str]:
        if _CANCELACION.search(e["mensaje"]):
            return "cancelacion", 0.9, "reglas"
        return "otro", 0.5, "reglas"

    async def clasificar(e: Estado) -> dict[str, Any]:
        """Cascada SVM → LLM (ml/README.md): el SVM del ml-service da la intención en milisegundos; si duda
        (confianza < umbral) o no responde, decide el clasificador LLM (sin cliente) o las reglas (con
        cliente, para no sumar latencia). Medido en notas únicas: SVM 0,73 · LLM 0,94 · cascada 0,92 con
        solo el 8 % de las notas al LLM. Sin cliente siempre hay una llamada LLM mínima de alcance, EN
        PARALELO con la búsqueda (el LLM del agente recibe las fuentes desde la primera llamada)."""
        get_stream_writer()({"tipo": "estado", "paso": "clasificando"})
        tarea_ml = asyncio.ensure_future(ml.intencion(e["mensaje_llm"]))  # texto ya sin PII (marcadores)
        buscar = e["ruta"] == "agente"
        if e.get("cliente_id"):
            # Con un cliente identificado el tema es de atención por definición: sin guardia de alcance.
            intencion, confianza, origen = intencion_ml(await tarea_ml) or intencion_reglas(e)
            precarga = []
            if buscar and intencion == "cancelacion":  # para citar la política de retención
                precarga = await retriever.buscar(
                    f"Política de retención de clientes ofertas {e['mensaje_llm']}"
                )
            return {
                "intencion": intencion,
                "confianza_intencion": confianza,
                "origen_intencion": origen,
                "precarga": precarga,
            }
        tarea_busqueda = asyncio.ensure_future(retriever.buscar(e["mensaje_llm"])) if buscar else None
        decision = intencion_ml(await tarea_ml)  # ~10 ms; la búsqueda ya está en curso
        p = prompts.cargar("alcance" if decision is not None else "clasificador")
        r = await llm.chat(
            s.modelo_economico,
            [{"role": "user", "content": p.render(mensaje=e["mensaje_llm"])}],
            e["uso"],
            json_mode=True,
            temperatura=0,
        )
        precarga = await tarea_busqueda if tarea_busqueda else []
        try:
            datos = json.loads(r.contenido)
        except json.JSONDecodeError:
            datos = {}
        if decision is None:  # SVM dudoso o caído: el clasificador LLM da la intención
            llm_int = datos.get("intencion")
            decision = (
                (llm_int, float(datos.get("confianza", 0.5)), "llm")
                if llm_int in INTENCIONES
                else intencion_reglas(e)
            )
        intencion, confianza, origen = decision or intencion_reglas(e)
        cambios: dict[str, Any] = {
            "intencion": intencion,
            "confianza_intencion": confianza,
            "origen_intencion": origen,
            "precarga": precarga,
        }
        if buscar and datos.get("fuera_de_alcance") is True:
            cambios.update(ruta="fuera_alcance", motivo="FUERA_DE_ALCANCE")
        return cambios

    async def rechazar(e: Estado) -> dict[str, Any]:
        texto = RESPUESTA_BLOQUEO if e["ruta"] == "bloqueado" else RESPUESTA_FUERA_ALCANCE
        await emitir_token(texto)
        return {"respuesta": texto, "confianza": 1.0, "modelo": "reglas", "citadas": [], "sin_cita": False}

    async def escalar(e: Estado) -> dict[str, Any]:
        """Escalamiento obligatorio: respuesta determinística + cita de la política + propuesta de ticket."""
        w = get_stream_writer()
        w({"tipo": "estado", "paso": "escalando"})
        frags = await retriever.buscar(
            "Política de Escalamiento: escalamiento obligatorio a supervisor humano "
            f"{e['detalle']} tiempos de atención SLA respuesta de supervisor",
            k=5,
        )
        politica = [f for f in frags if "escalamiento" in f.doc_id][:2] or frags[:1]
        fuentes = [{"n": i, **f.cita(), "texto": f.texto} for i, f in enumerate(politica, start=1)]
        cita = " [1]" if fuentes else ""
        sla = next((i for i, f in enumerate(politica, start=1) if "10 minutos" in f.texto), None)
        texto = (
            f"⚠️ Escalamiento obligatorio a supervisor: el mensaje indica {e['detalle']}.{cita}\n"
            f"- Debes escalar el caso a un supervisor humano{cita}"
            + (f"; el supervisor responde en máximo 10 minutos [{sla}]" if sla else "")
            + ".\n"
            "- Mantén un tono empático, no discutas la amenaza o la queja y no prometas soluciones.\n"
            "- No compartas datos del cliente ni de terceros hasta validar al titular."
        )
        propuestas = []
        advertencias = list(e.get("advertencias", []))
        if e.get("cliente_id"):
            categoria = CATEGORIA_TICKET.get(e.get("intencion", ""), "cancelacion")
            args = {
                "cliente_id": e["cliente_id"],
                "categoria": categoria,
                "prioridad": "prioritaria",
                "escalar_a": "supervisor",
                "descripcion": f"Escalamiento obligatorio ({e['motivo']}): {e['detalle']}.",
            }
            ok, datos, err = await mcp.llamar("crearTicket", args)
            if ok and isinstance(datos, dict) and datos.get("estado") == "requiere_confirmacion":
                pid = await guardar_propuesta(
                    {
                        **datos,
                        "argumentos": args,
                        "sesion_id": e["sesion_id"],
                        "usuario": e["usuario"]["id"],
                        "cliente_id": e["cliente_id"],
                    }
                )
                propuestas.append(
                    {"propuesta_id": pid, **{k: datos[k] for k in ("accion", "resumen", "requiere_rol")}}
                )
                w({"tipo": "propuesta", **propuestas[-1]})
                texto += (
                    "\n- Propuesta lista: ticket de escalamiento a supervisor (confírmala en la interfaz)."
                )
            elif not ok:
                advertencias.append(f"No se pudo preparar el ticket de escalamiento: {err}")
        await emitir_token(texto)
        return {
            "respuesta": texto,
            "fuentes": fuentes,
            "propuestas": propuestas,
            "confianza": 1.0,
            "modelo": "reglas",
            "advertencias": advertencias,
        }

    async def agente(e: Estado) -> dict[str, Any]:
        w = get_stream_writer()
        boveda = Boveda(e["boveda"])
        multi = bool(e.get("cliente_id")) or e.get("intencion") == "cancelacion"
        modelo = s.modelo_alto if multi else s.modelo_economico  # ruteo por complejidad (SAD 2.7)
        herramientas = await mcp.herramientas()
        escritura = {h["nombre"] for h in herramientas if h["escritura"]}
        tools_llm = [BUSCAR_CONOCIMIENTO] + [a_formato_llm(h) for h in herramientas]
        sistema = prompts.cargar("sistema").render(fecha=fecha_referencia)
        mensajes: list[dict[str, Any]] = [
            {"role": "system", "content": sistema},
            *e.get("historial", []),
            {"role": "user", "content": e["mensaje_llm"]},
        ]
        fuentes: list[dict[str, Any]] = []
        vistos: dict[str, int] = {}
        tools_log, propuestas = [], []
        advertencias = list(e.get("advertencias", []))
        conteo: Counter[str] = Counter()
        respuesta = ""
        riesgo_churn: dict[str, Any] | None = None

        def numerar(frags: list[Fragmento]) -> str:
            """Numeración global [n] entre búsquedas del mismo turno (sin duplicar fragmentos)."""
            numerados = []
            for f in frags:
                if f.id not in vistos:
                    vistos[f.id] = len(fuentes) + 1
                    fuentes.append({"n": vistos[f.id], **f.cita(), "texto": f.texto})
                numerados.append((vistos[f.id], f))
            return _formatear_fragmentos(numerados)

        async def es_del_cliente(nombre: str, args: dict[str, Any]) -> bool:
            """Acción con efecto solo sobre el cliente identificado en la conversación: el LLM no inventa
            el cliente (visto en pruebas) ni ajusta la factura de otro titular (datos de terceros)."""
            cliente = e.get("cliente_id")
            if not cliente:
                return False
            if "cliente_id" in args:
                return str(args["cliente_id"]).upper() == cliente
            if nombre == "aplicarAjuste" and args.get("factura_id"):
                ok, factura, _ = await mcp.llamar("obtenerFactura", {"factura_id": args["factura_id"]})
                return ok and isinstance(factura, dict) and factura.get("cliente_id") == cliente
            return False

        async def proponer(datos: dict[str, Any], argumentos: dict[str, Any]) -> dict[str, Any]:
            pid = await guardar_propuesta(
                {
                    **datos,
                    "argumentos": argumentos,
                    "sesion_id": e["sesion_id"],
                    "usuario": e["usuario"]["id"],
                    "cliente_id": e.get("cliente_id"),
                }
            )
            prop = {"propuesta_id": pid, **{k: datos[k] for k in ("accion", "resumen", "requiere_rol")}}
            propuestas.append(prop)
            w({"tipo": "propuesta", **prop})
            return prop

        async def visita_obligatoria(evaluacion: dict[str, Any], resultado: Any) -> Any:
            """POL-RET-2026 numeral 4, en código: ≥ 3 tickets técnicos en 90 días → visita técnica prioritaria
            (24 h) ANTES de un descuento. La propuesta se genera sin depender de que el LLM la pida."""
            visita = evaluacion.get("visita_tecnica_prioritaria") or {}
            if not visita.get("requerida") or visita.get("agendada"):
                return resultado
            if any(p["accion"] == "crearTicket" for p in propuestas):
                return resultado
            args = {
                "cliente_id": evaluacion["cliente_id"],
                "categoria": "soporte_tecnico",
                "prioridad": "prioritaria",
                "escalar_a": "nivel2",
                "descripcion": f"Visita técnica prioritaria (24 h) por {visita.get('tickets_tecnicos_90d')} "
                "tickets de soporte técnico en 90 días, previa a la oferta de retención (POL-RET-2026).",
            }
            inicio = time.perf_counter()
            ok, datos, error = await mcp.llamar("crearTicket", args)
            tools_log.append(
                {
                    "nombre": "crearTicket",
                    "ok": ok,
                    "error": (error or "")[:120] or None,
                    "ms": round((time.perf_counter() - inicio) * 1000, 1),
                    "argumentos": sorted(args),
                    "automatica": True,
                }
            )
            if not (ok and isinstance(datos, dict) and datos.get("estado") == "requiere_confirmacion"):
                advertencias.append(f"No se pudo preparar la visita técnica: {error}")
                return resultado
            await proponer(datos, args)
            return {
                "evaluacion": resultado,
                "visita_tecnica_propuesta": {
                    "estado": "requiere_confirmacion",
                    "resumen": datos["resumen"],
                    "instruccion": "Ya se preparó la propuesta de visita técnica prioritaria: dile al asesor "
                    "que la confirme en la interfaz; el descuento se ofrece después de la visita.",
                },
            }

        if e.get("intencion") == "cancelacion" and e.get("cliente_id"):
            # POL-RET-2026 en código: la skill se ejecuta SIEMPRE (no depende de que el LLM la elija; en
            # pruebas a veces consultaba solo los tickets y se saltaba la propuesta de visita técnica).
            # La ficha (obtenerCliente) corre en paralelo: alimenta la señal de riesgo de churn (ml-service).
            async def automatica(nombre: str) -> tuple[bool, Any, str | None]:
                conteo[nombre] += 1
                inicio = time.perf_counter()
                r = await mcp.llamar(nombre, {"cliente_id": e["cliente_id"]})
                tools_log.append(
                    {
                        "nombre": nombre,
                        "ok": r[0],
                        "error": (r[2] or "")[:120] or None,
                        "ms": round((time.perf_counter() - inicio) * 1000, 1),
                        "argumentos": ["cliente_id"],
                        "automatica": True,
                    }
                )
                return r

            (ok, datos, error), (ok_f, ficha, _) = await asyncio.gather(
                automatica("evaluarRetencion"), automatica("obtenerCliente")
            )
            if ok_f and isinstance(ficha, dict):
                riesgo_churn = await ml.churn(ficha)
            resultado_eval: Any = datos if ok else {"error": error}
            if ok and isinstance(datos, dict):
                resultado_eval = await visita_obligatoria(datos, datos)
            if riesgo_churn:
                resultado_eval = {
                    "retencion": resultado_eval,
                    "ficha_cliente": ficha,
                    "riesgo_churn": {
                        **{k: riesgo_churn.get(k) for k in ("nivel", "probabilidad", "factores")},
                        "uso": "Solo prioriza la atención; la elegibilidad la decide POL-RET-2026.",
                    },
                }
            elif ok_f:
                resultado_eval = {"retencion": resultado_eval, "ficha_cliente": ficha}
            mensajes.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "skill_retencion",
                            "type": "function",
                            "function": {
                                "name": "evaluarRetencion",
                                "arguments": json.dumps({"cliente_id": e["cliente_id"]}),
                            },
                        }
                    ],
                }
            )
            mensajes.append(
                {
                    "role": "tool",
                    "tool_call_id": "skill_retencion",
                    "content": json.dumps(resultado_eval, ensure_ascii=False, default=str)[:12000],
                }
            )

        if e.get("precarga"):  # la búsqueda ya corrió en paralelo: se presenta como una llamada hecha
            conteo["buscar_conocimiento"] += 1
            mensajes.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "precarga",
                            "type": "function",
                            "function": {
                                "name": "buscar_conocimiento",
                                "arguments": json.dumps({"consulta": e["mensaje_llm"]}, ensure_ascii=False),
                            },
                        }
                    ],
                }
            )
            mensajes.append({"role": "tool", "tool_call_id": "precarga", "content": numerar(e["precarga"])})
            tools_log.append(
                {
                    "nombre": "buscar_conocimiento",
                    "ok": True,
                    "error": None,
                    "ms": 0.0,
                    "argumentos": ["consulta"],
                    "precarga": True,
                }
            )

        for paso in range(s.max_pasos + 1):
            w({"tipo": "estado", "paso": "pensando" if paso == 0 else f"paso {paso + 1}"})
            ultimo = paso == s.max_pasos
            r = await llm.chat(
                modelo, mensajes, e["uso"], tools=None if ultimo else tools_llm, al_token=emitir_token
            )
            if not r.tool_calls:
                respuesta = r.contenido
                break
            if r.contenido:
                w({"tipo": "reiniciar"})  # texto previo a las tools: no es la respuesta final
            mensajes.append(
                {
                    "role": "assistant",
                    "content": r.contenido or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["nombre"],
                                "arguments": json.dumps(tc["argumentos"], ensure_ascii=False),
                            },
                        }
                        for tc in r.tool_calls
                    ],
                }
            )
            for tc in r.tool_calls:
                nombre, args = tc["nombre"], tc["argumentos"]
                conteo[nombre] += 1
                inicio = time.perf_counter()
                ok, error = True, None
                if conteo[nombre] > s.max_llamadas_misma_tool:
                    ok, error = False, "LIMITE_LLAMADAS"
                    resultado: Any = {
                        "error": f"Límite de {s.max_llamadas_misma_tool} llamadas a {nombre} en este "
                        "turno: responde con lo que tienes o indica que se escale."
                    }
                    advertencias.append(f"bucle cortado en {nombre}")
                elif nombre == "buscar_conocimiento":
                    w({"tipo": "estado", "paso": "buscando en fuentes"})
                    resultado = numerar(await retriever.buscar(str(args.get("consulta", e["mensaje_llm"]))))
                elif nombre in escritura and not await es_del_cliente(nombre, args):
                    # Una acción con efecto solo sobre el cliente identificado en la conversación: el LLM no
                    # puede inventar ni cambiar el cliente (visto en pruebas: proponía tickets sin cliente).
                    ok, error = False, "CLIENTE_NO_IDENTIFICADO"
                    resultado = {
                        "error": "No hay un cliente identificado en la conversación para esta acción. "
                        "Responde con el procedimiento y pide al asesor el ID del cliente (C-XXXX)."
                    }
                    advertencias.append(f"{nombre} rechazada: cliente no identificado")
                else:
                    w({"tipo": "estado", "paso": f"consultando {nombre}"})
                    ok, datos, error = await mcp.llamar(nombre, boveda.restituir(args))
                    if (
                        ok
                        and nombre in escritura
                        and isinstance(datos, dict)
                        and datos.get("estado") == "requiere_confirmacion"
                    ):
                        await proponer(datos, boveda.restituir(args))
                        resultado = {
                            "estado": "requiere_confirmacion",
                            "resumen": datos["resumen"],
                            "requiere_rol": datos["requiere_rol"],
                            "instruccion": "Propuesta registrada. Dile al asesor que la confirme en la "
                            "interfaz.",
                        }
                    else:
                        resultado = datos if ok else {"error": error}
                    if ok and nombre == "evaluarRetencion" and isinstance(datos, dict):
                        resultado = await visita_obligatoria(datos, resultado)
                tools_log.append(
                    {
                        "nombre": nombre,
                        "ok": ok,
                        "error": (error or "")[:120] or None,
                        "ms": round((time.perf_counter() - inicio) * 1000, 1),
                        "argumentos": sorted(args),
                    }
                )  # nombres, no valores (pueden ser PII)
                w({"tipo": "tool", "nombre": nombre, "ok": ok})
                mensajes.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": (
                            resultado
                            if isinstance(resultado, str)
                            else json.dumps(resultado, ensure_ascii=False, default=str)
                        )[:12000],
                    }
                )
        return {
            "respuesta": respuesta,
            "fuentes": fuentes,
            "tools": tools_log,
            "propuestas": propuestas,
            "modelo": modelo,
            "advertencias": advertencias,
            "riesgo_churn": (
                {k: riesgo_churn.get(k) for k in ("nivel", "probabilidad", "factores", "version")}
                if riesgo_churn
                else None
            ),
        }

    async def salida(e: Estado) -> dict[str, Any]:
        """Citas válidas, confianza y PII. Confianza baja → 'no encontrado → escalar'."""
        w = get_stream_writer()
        texto, citadas, invalidas = validar_citas(e.get("respuesta", ""), len(e.get("fuentes", [])))
        advertencias = list(e.get("advertencias", []))
        if invalidas:
            advertencias.append(f"citas inválidas eliminadas: {sorted(set(invalidas))}")
        fuentes = e.get("fuentes", [])
        confianza = e.get("confianza")
        if confianza is None:  # ruta agente
            # Un "no encontrado" del sistema (CLIENTE_NO_ENCONTRADO, FACTURA_NO_ENCONTRADA…) es una respuesta
            # concluyente, no falta de información: sin esto, "no existe un cliente con ese documento (CRM)"
            # se reemplazaba por "no encontré, escala". Errores técnicos (503, timeout) sí bajan la confianza.
            tools_ok = [
                t
                for t in e.get("tools", [])
                if t["nombre"] != "buscar_conocimiento" and (t["ok"] or _es_no_encontrado(t.get("error")))
            ]
            rel_citadas = [f["relevancia"] for f in fuentes if f["n"] in citadas]
            rel_todas = [f["relevancia"] for f in fuentes]
            conf_fuentes = max(rel_citadas) if rel_citadas else (max(rel_todas) * 0.6 if rel_todas else 0.0)
            confianza = max(conf_fuentes, 0.9 if tools_ok else 0.0)
        ruta, motivo = e["ruta"], e.get("motivo")
        if ruta == "agente" and confianza < s.umbral_confianza and not e.get("propuestas"):
            texto, ruta, motivo = RESPUESTA_NO_ENCONTRADO, "escalar", "BAJA_CONFIANZA"
            w({"tipo": "reemplazar", "texto": texto})
        texto_seguro = redactar(texto)
        if texto_seguro != texto:
            advertencias.append("PII redactada en la salida")
            w({"tipo": "reemplazar", "texto": texto_seguro})
        sin_cita = bool(fuentes) and not citadas and ruta == "agente"
        w(
            {
                "tipo": "fuentes",
                "fuentes": [
                    {k: v for k, v in f.items() if k != "texto"} | {"citada": f["n"] in citadas}
                    for f in fuentes
                ],
            }
        )
        return {
            "respuesta": texto_seguro,
            "confianza": round(float(confianza), 3),
            "citadas": sorted(citadas),
            "sin_cita": sin_cita,
            "advertencias": advertencias,
            "ruta": ruta,
            "motivo": motivo,
        }

    # ------------------------------------------------------------------------- grafo ------

    g = StateGraph(Estado)
    for nombre, fn in [
        ("entrada", entrada),
        ("clasificar", clasificar),
        ("rechazar", rechazar),
        ("escalar", escalar),
        ("agente", agente),
        ("salida", salida),
    ]:
        g.add_node(nombre, nodo(nombre, fn))  # un span por nodo en Phoenix
    g.add_edge(START, "entrada")
    g.add_conditional_edges(
        "entrada",
        lambda e: "rechazar" if e["ruta"] == "bloqueado" else "clasificar",
        {"rechazar": "rechazar", "clasificar": "clasificar"},
    )
    g.add_conditional_edges(
        "clasificar",
        lambda e: {"fuera_alcance": "rechazar", "escalar": "escalar"}.get(e["ruta"], "agente"),
        {"rechazar": "rechazar", "escalar": "escalar", "agente": "agente"},
    )
    g.add_edge("escalar", "salida")
    g.add_edge("agente", "salida")
    g.add_edge("rechazar", END)
    g.add_edge("salida", END)
    return g.compile()
