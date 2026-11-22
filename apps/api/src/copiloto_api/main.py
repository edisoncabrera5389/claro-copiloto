"""API FastAPI de Claro Copiloto.

POST /auth/login · POST /chat (SSE) · POST /chat/sincrono · GET /acciones/pendientes ·
POST /acciones/{id}/confirmar · POST /acciones/{id}/rechazar · POST /feedback ·
GET /conversaciones/{sesion} · GET /clientes/{id}/ficha · POST|GET /escalamientos ·
POST /escalamientos/{id}/atender · GET /metrics · GET /health · GET /health/vivo
"""

import asyncio
import json
import logging
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Path, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from copiloto_api import prompts
from copiloto_api.agente import crear_agente
from copiloto_api.config import Settings
from copiloto_api.confirmacion import Confirmaciones
from copiloto_api.llm import ClienteLLM
from copiloto_api.mcp_cliente import ClienteMCP
from copiloto_api.memoria import Memoria
from copiloto_api.ml_cliente import ClienteML
from copiloto_api.notificador import Notificador
from copiloto_api.observabilidad import Metricas, configurar_trazas, marcar_error, span
from copiloto_api.pii import redactar
from copiloto_api.rag import Retriever
from copiloto_api.seguridad import Usuario, autenticar, emitir_jwt, usuario_actual

log = logging.getLogger("copiloto_api")
ERRORES_TRANSITORIOS = ("CIRCUITO_ABIERTO", "SIN_CONEXION", "SERVICIO_NO_DISPONIBLE", "LIMITE_EXCEDIDO")
# Campos que pueden salir hacia n8n/ERP: identificadores, códigos y montos (nunca texto libre ni PII).
CAMPOS_RPA = (
    "cliente_id",
    "factura_id",
    "valor",
    "categoria",
    "prioridad",
    "escalar_a",
    "codigo",
    "servicio_id",
)
CAMPOS_RESULTADO_RPA = ("ticket_id", "ajuste_id", "oferta_id", "estado")


@dataclass
class Dependencias:
    llm: ClienteLLM
    retriever: Retriever
    mcp: ClienteMCP
    memoria: Memoria
    ml: ClienteML
    notificador: Notificador | None = None  # n8n (RPA); None → se arma con API_N8N_URL


class Login(BaseModel):
    usuario: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)


class Mensaje(BaseModel):
    mensaje: str = Field(min_length=1, max_length=2000)
    sesion_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{6,64}$")


class Escalamiento(BaseModel):
    sesion_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{6,64}$")
    motivo: str | None = Field(default=None, max_length=300)


class Feedback(BaseModel):
    turno_id: str = Field(min_length=6, max_length=64)
    valor: Literal[1, -1]
    comentario: str | None = Field(default=None, max_length=500)


def _construir_dependencias(s: Settings) -> Dependencias:  # pragma: no cover - conexiones reales
    import redis.asyncio as aioredis
    from pymongo import MongoClient
    from qdrant_client import QdrantClient

    llm = ClienteLLM(s)
    retriever = Retriever(s, QdrantClient(url=s.qdrant_url, timeout=20), llm)
    memoria = Memoria(
        s,
        aioredis.from_url(s.redis_url, decode_responses=True),
        MongoClient(s.mongo_url, serverSelectionTimeoutMS=5000)[s.mongo_db],
    )
    return Dependencias(llm, retriever, ClienteMCP(s.mcp_url), memoria, ClienteML(s.ml_url, s.ml_timeout_s))


def anotar_traza(raiz: Any, r: dict[str, Any], final: dict[str, Any]) -> None:
    """Resumen del turno en el span raíz. Entrada = texto ENMASCARADO (el mismo que ve el LLM)."""
    raiz.set_attribute("session.id", r["sesion_id"])
    raiz.set_attribute("input.value", final.get("mensaje_llm", ""))
    raiz.set_attribute("output.value", r["respuesta"])
    raiz.set_attribute("llm.token_count.prompt", r["uso"]["tokens_entrada"])
    raiz.set_attribute("llm.token_count.completion", r["uso"]["tokens_salida"])
    raiz.set_attribute("llm.token_count.total", r["uso"]["tokens_entrada"] + r["uso"]["tokens_salida"])
    for clave in ("ruta", "motivo", "intencion", "cliente_id", "modelo", "confianza", "sin_cita"):
        if r.get(clave) is not None:
            raiz.set_attribute(f"copiloto.{clave}", r[clave])
    raiz.set_attribute("copiloto.origen_intencion", final.get("origen_intencion") or "")
    raiz.set_attribute("copiloto.costo_usd", r["uso"]["costo_usd"])
    raiz.set_attribute("copiloto.ttft_ms", r["latencias"]["ttft_ms"])
    raiz.set_attribute("copiloto.fuentes", ", ".join(f"{f['fuente']} v{f['version']}" for f in r["fuentes"]))
    raiz.set_attribute("copiloto.tools", ", ".join(t["nombre"] for t in r["tools"]))
    raiz.set_attribute("metadata", json.dumps({"prompts": prompts.versiones()}))
    if r["ruta"] == "bloqueado":
        raiz.set_attribute("copiloto.bloqueo", "prompt_injection")


def _cargar_reranker(s: Settings, retriever: Retriever, estado: dict[str, str]) -> None:  # pragma: no cover
    """En segundo plano: la primera vez descarga el modelo (~0,6 GB). Mientras tanto se busca sin rerank."""
    try:
        from copiloto_api.rag import RerankerFastembed

        retriever.reranker = RerankerFastembed(s.reranker_modelo, str(s.modelos_dir))
        estado["reranker"] = "listo"
    except Exception as e:
        estado["reranker"] = f"error: {type(e).__name__}"
        log.exception("No se pudo cargar el reranker")


def crear_app(settings: Settings | None = None, deps: Dependencias | None = None) -> FastAPI:
    s = settings or Settings()

    @asynccontextmanager
    async def ciclo(app: FastAPI):
        d = deps or _construir_dependencias(s)
        app.state.deps = d
        app.state.notificador = d.notificador or Notificador(s.n8n_url)
        app.state.estado = {"reranker": "desactivado" if not s.reranker_activo else "cargando"}
        if s.reranker_activo and d.retriever.reranker is None:
            threading.Thread(
                target=_cargar_reranker, args=(s, d.retriever, app.state.estado), daemon=True
            ).start()
        elif d.retriever.reranker is not None:
            app.state.estado["reranker"] = "listo"
        app.state.agente = crear_agente(s, d.llm, d.retriever, d.mcp, d.memoria.guardar_propuesta, d.ml)
        try:  # precalentar: el primer turno no paga el descubrimiento de tools del MCP
            await d.mcp.herramientas()
        except Exception as e:  # noqa: BLE001 - el MCP puede no estar listo aún; se reintenta en el primer turno
            log.warning("MCP no disponible al arrancar: %s", type(e).__name__)
        try:  # ...ni las conexiones de embeddings (LiteLLM → OpenAI) y Qdrant: medido, +1,2 s de TTFT en frío
            await d.retriever.buscar("precalentamiento del copiloto")
        except Exception as e:  # noqa: BLE001
            log.warning("Retriever no disponible al arrancar: %s", type(e).__name__)
        yield

    configurar_trazas(s.otel_endpoint, s.otel_proyecto)
    # Sin la telemetría nativa de FastAPI: sus spans HTTP (incluido GET /metrics cada 15 s y los healthchecks)
    # tapaban en Phoenix las trazas del agente. La traza útil empieza en el span "turno".
    app = FastAPI(
        title="Claro Copiloto API",
        version="0.1.0",
        lifespan=ciclo,
        telemetry={"tracing": False, "metrics": False, "logs": False},
    )
    app.state.settings = s
    app.state.metricas = metricas = Metricas()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:4200", "http://localhost:8080"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    UsuarioActual = Annotated[Usuario, Depends(usuario_actual)]

    def deps_de(request: Request) -> Dependencias:
        return request.app.state.deps

    async def limitar(request: Request, u: Usuario, recurso: str = "chat") -> None:
        if not await deps_de(request).memoria.permitir(u.id, recurso):
            raise HTTPException(
                429, "Demasiadas solicitudes; espera un minuto", headers={"Retry-After": "60"}
            )

    async def registrar_escalamiento(
        request: Request,
        sesion_id: str,
        turno_id: str | None,
        cliente_id: str | None,
        usuario: str,
        origen: str,
        motivo: str,
    ) -> str:
        """Cola del supervisor (Mongo) + métrica + evento a n8n. Motivo redactado (Ley 1581)."""
        motivo = redactar(motivo)
        eid = await deps_de(request).memoria.registrar_escalamiento(
            {
                "sesion_id": sesion_id,
                "turno_id": turno_id,
                "cliente_id": cliente_id,
                "motivo": motivo,
                "origen": origen,
                "usuario": usuario,
                "fecha": datetime.now(UTC),
            }
        )
        if origen == "manual":
            metricas.escalamientos.labels("manual", "MANUAL").inc()
        request.app.state.notificador.enviar(
            "escalamiento",
            {
                "escalamiento_id": eid,
                "origen": origen,
                "cliente_id": cliente_id,
                "motivo": motivo,
                "asesor": usuario,
                "sesion_id": sesion_id,
            },
        )
        return eid

    # ------------------------------------------------------------------ turno -------------
    async def ejecutar_turno(
        request: Request, u: Usuario, m: Mensaje, enviar: Callable[[str, dict[str, Any]], Awaitable[None]]
    ) -> dict[str, Any]:
        """Un turno = una traza en Phoenix (span AGENT raíz) + métricas + auditoría con el trace_id."""
        metricas.en_curso.inc()
        try:
            with span("turno", "AGENT", **{"user.id": u.id}) as raiz:
                try:
                    return await _turno(request, u, m, enviar, raiz)
                except Exception as e:
                    metricas.errores_turno.inc()
                    marcar_error(raiz, type(e).__name__)
                    raise
        finally:
            metricas.en_curso.dec()

    async def _turno(
        request: Request,
        u: Usuario,
        m: Mensaje,
        enviar: Callable[[str, dict[str, Any]], Awaitable[None]],
        raiz: Any,
    ) -> dict[str, Any]:
        d = deps_de(request)
        sesion_id = m.sesion_id or uuid.uuid4().hex[:16]
        turno_id = uuid.uuid4().hex
        inicio = time.perf_counter()
        ttft: float | None = None
        await enviar("inicio", {"sesion_id": sesion_id, "turno_id": turno_id})
        entrada = {
            "sesion_id": sesion_id,
            "usuario": u.dict(),
            "mensaje": m.mensaje,
            "historial": await d.memoria.historial(sesion_id),
        }
        final: dict[str, Any] = {}
        async for modo, dato in request.app.state.agente.astream(entrada, stream_mode=["custom", "values"]):
            if modo == "values":
                final = dato
                continue
            if dato["tipo"] == "token" and ttft is None:
                ttft = time.perf_counter() - inicio
            await enviar(dato["tipo"], {k: v for k, v in dato.items() if k != "tipo"})
        total = time.perf_counter() - inicio
        uso = final["uso"].dict()
        resultado = {
            "turno_id": turno_id,
            "sesion_id": sesion_id,
            "respuesta": final.get("respuesta", ""),
            "confianza": final.get("confianza"),
            "intencion": final.get("intencion"),
            "cliente_id": final.get("cliente_id"),
            "riesgo_churn": final.get("riesgo_churn"),
            "ruta": final.get("ruta"),
            "motivo": final.get("motivo"),
            "fuentes": [
                {k: v for k, v in f.items() if k != "texto"}
                | {"citada": f["n"] in final.get("citadas", []), "extracto": f.get("texto", "")[:600]}
                for f in final.get("fuentes", [])
            ],
            "tools": final.get("tools", []),
            "propuestas": final.get("propuestas", []),
            "sin_cita": final.get("sin_cita", False),
            "advertencias": final.get("advertencias", []),
            "modelo": final.get("modelo"),
            "uso": uso,
            "latencias": {"ttft_ms": round((ttft or total) * 1000), "total_ms": round(total * 1000)},
        }
        trace_id = format(raiz.get_span_context().trace_id, "032x")
        anotar_traza(raiz, resultado, final)
        metricas.registrar_turno(resultado, final.get("origen_intencion"))
        await d.memoria.agregar_turno(sesion_id, final.get("mensaje_llm", ""), resultado["respuesta"])
        await d.memoria.auditar_turno(
            {
                **{k: v for k, v in resultado.items() if k != "sesion_id"},
                "sesion_id": sesion_id,
                "usuario": u.id,
                "rol": u.rol,
                "fecha": datetime.now(UTC),
                "pregunta": final.get("mensaje_llm", ""),
                "cliente_id": final.get("cliente_id"),
                "confianza_intencion": final.get("confianza_intencion"),
                "origen_intencion": final.get("origen_intencion"),
                "citadas": final.get("citadas", []),
                "prompt_versions": prompts.versiones(),
                "reranker": request.app.state.estado.get("reranker"),
                "trace_id": trace_id,  # auditoría ↔ traza en Phoenix
            }
        )
        if resultado["ruta"] == "escalar" and resultado["motivo"] != "BAJA_CONFIANZA":
            # Escalamiento obligatorio por política: entra solo a la cola del supervisor y dispara n8n.
            await registrar_escalamiento(
                request,
                sesion_id,
                turno_id,
                resultado["cliente_id"],
                u.id,
                "politica",
                f"{resultado['motivo']}: {final.get('detalle') or 'escalamiento obligatorio'}",
            )
        log.info(
            json.dumps(
                {
                    "turno": turno_id,
                    "trace_id": trace_id,
                    "ruta": resultado["ruta"],
                    "intencion": resultado["intencion"],
                    "tools": [t["nombre"] for t in resultado["tools"]],
                    "fuentes": len(resultado["fuentes"]),
                    "confianza": resultado["confianza"],
                    **resultado["latencias"],
                    "costo_usd": uso["costo_usd"],
                },
                ensure_ascii=False,
            )
        )
        return resultado

    # ------------------------------------------------------------------ endpoints ---------
    @app.post("/auth/login")
    async def login(datos: Login, request: Request) -> dict[str, Any]:
        u = autenticar(s, datos.usuario, datos.password)
        if u is None:
            raise HTTPException(401, "Usuario o contraseña inválidos")
        return {"access_token": emitir_jwt(s, u), "token_type": "bearer", "usuario": u.dict()}

    @app.post("/chat")
    async def chat(m: Mensaje, request: Request, u: UsuarioActual) -> EventSourceResponse:
        await limitar(request, u)
        cola: asyncio.Queue = asyncio.Queue()

        async def enviar(evento: str, datos: dict[str, Any]) -> None:
            await cola.put({"event": evento, "data": json.dumps(datos, ensure_ascii=False, default=str)})

        async def producir() -> None:
            try:
                resultado = await ejecutar_turno(request, u, m, enviar)
                await enviar("fin", resultado)
            except Exception as e:  # el cliente recibe un error legible, no un corte del stream
                log.exception("Error en el turno")
                await enviar(
                    "error", {"mensaje": "No se pudo completar la respuesta", "tipo": type(e).__name__}
                )
            finally:
                await cola.put(None)

        async def eventos():
            tarea = asyncio.create_task(producir())
            try:
                while (item := await cola.get()) is not None:
                    yield item
            finally:
                # Si el asesor cierra la pestaña o sale a mitad del turno, el turno termina igual: se audita y
                # queda en memoria (sin shield, al cortarse el stream se cancelaba el turno sin auditar).
                await asyncio.shield(tarea)

        return EventSourceResponse(eventos(), ping=15)

    @app.post("/chat/sincrono")
    async def chat_sincrono(m: Mensaje, request: Request, u: UsuarioActual) -> dict[str, Any]:
        """Mismo turno sin streaming (evaluación automática, integraciones)."""
        await limitar(request, u)

        async def nada(evento: str, datos: dict[str, Any]) -> None:
            return None

        return await ejecutar_turno(request, u, m, nada)

    @app.get("/acciones/pendientes")
    async def pendientes(request: Request, u: UsuarioActual) -> list[dict[str, Any]]:
        return await deps_de(request).memoria.pendientes(u.id, u.rol)

    @app.post("/acciones/{pid}/confirmar")
    async def confirmar(pid: str, request: Request, u: UsuarioActual) -> dict[str, Any]:
        """El asesor (o supervisor) confirma: la API firma el token que exige el MCP y ejecuta una vez."""
        d = deps_de(request)
        p = await d.memoria.propuesta(pid)
        if p is None:
            raise HTTPException(404, "La propuesta no existe o expiró")
        es_supervisor = u.rol in ("supervisor", "admin")
        if p["requiere_rol"] == "supervisor" and not es_supervisor:
            raise HTTPException(403, "Esta acción requiere la confirmación de un supervisor")
        if not es_supervisor and p.get("usuario") != u.id:
            raise HTTPException(403, "Solo quien originó la propuesta (o un supervisor) puede confirmarla")
        p = await d.memoria.tomar_propuesta(pid)
        if p is None:
            raise HTTPException(409, "La propuesta ya fue atendida")
        token = Confirmaciones(s.confirmacion_secret.get_secret_value(), s.confirmacion_ttl_s).emitir(
            p["accion"], p["parametros"], u.id, "supervisor" if es_supervisor else "asesor"
        )
        ok, datos, error = await d.mcp.llamar(p["accion"], {**p["argumentos"], "token_confirmacion": token})
        await d.memoria.registrar_accion(
            {
                "propuesta_id": pid,
                "accion": p["accion"],
                "parametros": p["parametros"],
                "sesion_id": p.get("sesion_id"),
                "propuesta_por": p.get("usuario"),
                "confirmada_por": u.id,
                "rol": u.rol,
                "ok": ok,
                "error": error,
                "fecha": datetime.now(UTC),
            }
        )
        metricas.acciones.labels(p["accion"], "ejecutada" if ok else "error").inc()
        if not ok:
            if error and error.startswith(ERRORES_TRANSITORIOS):
                await d.memoria.devolver_propuesta(p)  # no se aplicó: puede reintentar
            raise HTTPException(
                502 if error and error.startswith(ERRORES_TRANSITORIOS) else 409,
                error or "La acción no se pudo ejecutar",
            )
        # RPA (n8n → ERP): visita técnica → orden de servicio; ajuste → nota crédito. Solo campos permitidos.
        # El MCP anida la respuesta del sistema (ticket, ajuste) en "resultado".
        resultado_rpa = datos.get("resultado") if isinstance(datos, dict) else None
        resultado_rpa = resultado_rpa if isinstance(resultado_rpa, dict) else {}
        request.app.state.notificador.enviar(
            "accion-confirmada",
            {
                "accion": p["accion"],
                "propuesta_id": pid,
                "cliente_id": p.get("cliente_id") or p["parametros"].get("cliente_id"),
                "confirmada_por": u.id,
                "rol": u.rol,
                "parametros": {k: p["parametros"][k] for k in CAMPOS_RPA if k in p["parametros"]},
                "resultado": {k: resultado_rpa[k] for k in CAMPOS_RESULTADO_RPA if k in resultado_rpa},
            },
        )
        return {"estado": "ejecutada", "accion": p["accion"], "resultado": datos}

    @app.post("/acciones/{pid}/rechazar")
    async def rechazar(pid: str, request: Request, u: UsuarioActual) -> dict[str, str]:
        d = deps_de(request)
        p = await d.memoria.tomar_propuesta(pid)
        if p is None:
            raise HTTPException(404, "La propuesta no existe o expiró")
        await d.memoria.registrar_accion(
            {
                "propuesta_id": pid,
                "accion": p["accion"],
                "rechazada_por": u.id,
                "rol": u.rol,
                "ok": False,
                "error": "RECHAZADA",
                "fecha": datetime.now(UTC),
            }
        )
        metricas.acciones.labels(p["accion"], "rechazada").inc()
        return {"estado": "rechazada"}

    @app.post("/feedback")
    async def feedback(f: Feedback, request: Request, u: UsuarioActual) -> dict[str, str]:
        d = deps_de(request)
        if await d.memoria.turno(f.turno_id) is None:
            raise HTTPException(404, "Turno no encontrado")
        await d.memoria.registrar_feedback({**f.model_dump(), "usuario": u.id, "fecha": datetime.now(UTC)})
        metricas.feedback.labels("positivo" if f.valor == 1 else "negativo").inc()
        return {"estado": "registrado"}

    @app.get("/conversaciones/{sesion_id}")
    async def conversacion(sesion_id: str, request: Request, u: UsuarioActual) -> list[dict[str, Any]]:
        return await deps_de(request).memoria.conversacion(sesion_id, u.id, u.rol)

    def exigir_supervisor(u: Usuario) -> None:
        if u.rol not in ("supervisor", "admin"):
            raise HTTPException(403, "Solo un supervisor puede ver o atender escalamientos")

    @app.get("/clientes/{cliente_id}/ficha")
    async def ficha(
        request: Request, u: UsuarioActual, cliente_id: Annotated[str, Path(pattern=r"^C-\d{4}$")]
    ) -> dict[str, Any]:
        """Panel de la ficha del cliente en el front: lecturas del MCP en paralelo (PII ya filtrada)."""
        await limitar(request, u, "ficha")
        d = deps_de(request)
        (ok_c, cliente, err_c), (ok_s, saldo, _), (ok_f, facturas, _) = await asyncio.gather(
            d.mcp.llamar("obtenerCliente", {"cliente_id": cliente_id}),
            d.mcp.llamar("obtenerSaldo", {"cliente_id": cliente_id}),
            d.mcp.llamar("listarFacturas", {"cliente_id": cliente_id, "limite": 3}),
        )
        if not ok_c:
            no_existe = "NO_ENCONTRADO" in (err_c or "")
            raise HTTPException(404 if no_existe else 502, err_c or "No se pudo consultar el CRM")
        return {
            "cliente": cliente,
            "saldo": saldo if ok_s else None,
            "facturas": facturas if ok_f else None,
        }

    @app.post("/escalamientos")
    async def escalar(e: Escalamiento, request: Request, u: UsuarioActual) -> dict[str, str]:
        """Botón "Escalar" del asesor: el caso entra a la cola del supervisor con el contexto del turno."""
        ultimo = await deps_de(request).memoria.ultimo_turno(e.sesion_id, u.id) or {}
        eid = await registrar_escalamiento(
            request,
            e.sesion_id,
            ultimo.get("turno_id"),
            ultimo.get("cliente_id"),
            u.id,
            "manual",
            e.motivo or "Escalamiento manual del asesor",
        )
        return {"escalamiento_id": eid, "estado": "abierto"}

    @app.get("/escalamientos")
    async def escalamientos(request: Request, u: UsuarioActual) -> list[dict[str, Any]]:
        exigir_supervisor(u)
        return await deps_de(request).memoria.escalamientos()

    @app.post("/escalamientos/{eid}/atender")
    async def atender(eid: str, request: Request, u: UsuarioActual) -> dict[str, str]:
        exigir_supervisor(u)
        if not await deps_de(request).memoria.atender_escalamiento(eid, u.id, datetime.now(UTC)):
            raise HTTPException(404, "El escalamiento no existe o ya fue atendido")
        return {"estado": "atendido"}

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        """Prometheus (red interna; Nginx no lo expone hacia el navegador)."""
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return Response(generate_latest(metricas.registro), media_type=CONTENT_TYPE_LATEST)

    @app.get("/health/vivo")
    async def vivo() -> dict[str, str]:
        return {"estado": "ok"}

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        d = deps_de(request)
        componentes: dict[str, str] = {"reranker": request.app.state.estado.get("reranker", "?")}
        try:
            await d.memoria.r.ping()
            componentes["redis"] = "ok"
        except Exception as e:  # noqa: BLE001
            componentes["redis"] = f"error: {type(e).__name__}"
        return {"estado": "ok", "componentes": componentes, "prompts": prompts.versiones()}

    return app
