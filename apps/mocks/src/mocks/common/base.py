"""Aplicación base: autenticación, límite 429, falla simulada 503, trazas y logs sin PII.

Orden del pipeline por solicitud:  X-API-Key (401) → límite (429) → falla simulada (503) → handler.
El 503 se decide ANTES del handler: un POST que recibe 503 no tuvo efecto y puede reintentarse.
"""

import hmac
import json
import logging
import random
import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, Field

from mocks.common.config import Settings
from mocks.common.errors import registrar_manejadores, respuesta_error
from mocks.common.ratelimit import RateLimiter

log = logging.getLogger("mocks.http")

RUTAS_PUBLICAS = {"/health", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
_TRACEPARENT = re.compile(r"^[0-9a-f]{2}-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$")


class ConfigCaos(BaseModel):
    fail_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    rate_limit_per_min: int | None = Field(default=None, ge=1)


def _trace_id(request: Request) -> str:
    """Reutiliza el trace-id W3C (traceparent) si llega; si no, genera uno."""
    m = _TRACEPARENT.match(request.headers.get("traceparent", ""))
    return m.group(1) if m else uuid.uuid4().hex


def crear_app_base(
    servicio: str,
    titulo: str,
    settings: Settings,
    cargar_estado: Callable[[], object],
) -> FastAPI:
    """Crea la app con el pipeline de resiliencia. `cargar_estado` construye el estado en memoria."""
    app = FastAPI(title=titulo, version="1.0.0", description=f"Servicio simulado: {servicio}")
    app.state.settings = settings
    app.state.servicio = servicio
    app.state.fail_rate = settings.fail_rate
    app.state.limiter = RateLimiter(settings.rate_limit_per_min)
    app.state.rng = random.Random(settings.seed)  # noqa: S311 - simulación, no criptografía
    app.state.cargar_estado = cargar_estado
    app.state.datos = cargar_estado()
    registrar_manejadores(app)
    clave_esperada = settings.api_key.get_secret_value().encode()

    async def _pipeline(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        trace_id = request.state.trace_id
        ruta = request.url.path
        if ruta in RUTAS_PUBLICAS:
            return await call_next(request)

        clave = request.headers.get("X-API-Key", "")
        if not clave or not hmac.compare_digest(clave.encode(), clave_esperada):
            return respuesta_error(trace_id, 401, "NO_AUTORIZADO", "API key ausente o inválida")

        if ruta.startswith("/_admin"):  # control de la demo: sin límite ni falla simulada
            return await call_next(request)

        limiter: RateLimiter = app.state.limiter
        permitida, retry_after, restantes = limiter.consumir(clave)
        if not permitida:
            return respuesta_error(
                trace_id,
                429,
                "LIMITE_EXCEDIDO",
                f"Se excedió el límite de {limiter.limite} solicitudes por minuto",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limiter.limite),
                    "X-RateLimit-Remaining": "0",
                },
            )

        if app.state.rng.random() < app.state.fail_rate:
            return respuesta_error(
                trace_id, 503, "SERVICIO_NO_DISPONIBLE", "Servicio temporalmente no disponible (simulado)"
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limiter.limite)
        response.headers["X-RateLimit-Remaining"] = str(restantes)
        return response

    @app.middleware("http")
    async def resiliencia(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request.state.trace_id = _trace_id(request)
        inicio = time.perf_counter()
        response = await _pipeline(request, call_next)
        response.headers["X-Trace-Id"] = request.state.trace_id
        # Nunca se registra la query string: /clientes?numero_documento=... es PII.
        log.info(
            json.dumps(
                {
                    "servicio": servicio,
                    "metodo": request.method,
                    "ruta": request.url.path,
                    "status": response.status_code,
                    "ms": round((time.perf_counter() - inicio) * 1000, 1),
                    "trace_id": request.state.trace_id,
                },
                ensure_ascii=False,
            )
        )
        return response

    @app.get("/health", include_in_schema=False)
    async def health() -> dict:
        return {"estado": "ok", "servicio": servicio}

    @app.get("/_admin/config", include_in_schema=False)
    async def leer_config() -> dict:
        return {"fail_rate": app.state.fail_rate, "rate_limit_per_min": app.state.limiter.limite}

    @app.put("/_admin/config", include_in_schema=False)
    async def cambiar_config(cfg: ConfigCaos) -> dict:
        """Permite en la demo subir el 503 al 100 % o bajar el límite sin reiniciar el contenedor."""
        if cfg.fail_rate is not None:
            app.state.fail_rate = cfg.fail_rate
        if cfg.rate_limit_per_min is not None:
            app.state.limiter.limite = cfg.rate_limit_per_min
        return await leer_config()

    @app.post("/_admin/reset", include_in_schema=False)
    async def reset() -> dict:
        """Recarga los datos originales y limpia contadores (se pierde lo creado por los POST)."""
        app.state.datos = app.state.cargar_estado()
        app.state.limiter.reiniciar()
        return {"estado": "reiniciado"}

    return app
