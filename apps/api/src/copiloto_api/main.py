"""API FastAPI de Claro Copiloto.

POST /auth/login · POST /chat (SSE) · POST /chat/sincrono · GET /acciones/pendientes ·
POST /acciones/{id}/confirmar · POST /acciones/{id}/rechazar · POST /feedback ·
GET /conversaciones/{sesion} · GET /health · GET /health/vivo
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

from fastapi import Depends, FastAPI, HTTPException, Request
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
from copiloto_api.rag import Retriever
from copiloto_api.seguridad import Usuario, autenticar, emitir_jwt, usuario_actual

log = logging.getLogger("copiloto_api")
ERRORES_TRANSITORIOS = ("CIRCUITO_ABIERTO", "SIN_CONEXION", "SERVICIO_NO_DISPONIBLE", "LIMITE_EXCEDIDO")


@dataclass
class Dependencias:
    llm: ClienteLLM
    retriever: Retriever
    mcp: ClienteMCP
    memoria: Memoria


class Login(BaseModel):
    usuario: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)


class Mensaje(BaseModel):
    mensaje: str = Field(min_length=1, max_length=2000)
    sesion_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{6,64}$")


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
    return Dependencias(llm, retriever, ClienteMCP(s.mcp_url), memoria)


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
        app.state.estado = {"reranker": "desactivado" if not s.reranker_activo else "cargando"}
        if s.reranker_activo and d.retriever.reranker is None:
            threading.Thread(
                target=_cargar_reranker, args=(s, d.retriever, app.state.estado), daemon=True
            ).start()
        elif d.retriever.reranker is not None:
            app.state.estado["reranker"] = "listo"
        app.state.agente = crear_agente(s, d.llm, d.retriever, d.mcp, d.memoria.guardar_propuesta)
        try:  # precalentar: el primer turno no paga el descubrimiento de tools del MCP
            await d.mcp.herramientas()
        except Exception as e:  # noqa: BLE001 - el MCP puede no estar listo aún; se reintenta en el primer turno
            log.warning("MCP no disponible al arrancar: %s", type(e).__name__)
        yield

    app = FastAPI(title="Claro Copiloto API", version="0.1.0", lifespan=ciclo)
    app.state.settings = s
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:4200", "http://localhost:8080"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    UsuarioActual = Annotated[Usuario, Depends(usuario_actual)]

    def deps_de(request: Request) -> Dependencias:
        return request.app.state.deps

    async def limitar(request: Request, u: Usuario) -> None:
        if not await deps_de(request).memoria.permitir(u.id):
            raise HTTPException(
                429, "Demasiadas solicitudes; espera un minuto", headers={"Retry-After": "60"}
            )

    # ------------------------------------------------------------------ turno -------------
    async def ejecutar_turno(
        request: Request, u: Usuario, m: Mensaje, enviar: Callable[[str, dict[str, Any]], Awaitable[None]]
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
                "citadas": final.get("citadas", []),
                "prompt_versions": prompts.versiones(),
                "reranker": request.app.state.estado.get("reranker"),
            }
        )
        log.info(
            json.dumps(
                {
                    "turno": turno_id,
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
                await tarea

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
        if not ok:
            if error and error.startswith(ERRORES_TRANSITORIOS):
                await d.memoria.devolver_propuesta(p)  # no se aplicó: puede reintentar
            raise HTTPException(
                502 if error and error.startswith(ERRORES_TRANSITORIOS) else 409,
                error or "La acción no se pudo ejecutar",
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
        return {"estado": "rechazada"}

    @app.post("/feedback")
    async def feedback(f: Feedback, request: Request, u: UsuarioActual) -> dict[str, str]:
        d = deps_de(request)
        if await d.memoria.turno(f.turno_id) is None:
            raise HTTPException(404, "Turno no encontrado")
        await d.memoria.registrar_feedback({**f.model_dump(), "usuario": u.id, "fecha": datetime.now(UTC)})
        return {"estado": "registrado"}

    @app.get("/conversaciones/{sesion_id}")
    async def conversacion(sesion_id: str, request: Request, u: UsuarioActual) -> list[dict[str, Any]]:
        return await deps_de(request).memoria.conversacion(sesion_id, u.id, u.rol)

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
