"""Errores con el esquema del contrato: {codigo, mensaje, trace_id}."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("mocks.http")


class ApiError(Exception):
    """Error de negocio o de solicitud que se devuelve con el esquema Error."""

    def __init__(self, status: int, codigo: str, mensaje: str, headers: dict[str, str] | None = None):
        super().__init__(mensaje)
        self.status = status
        self.codigo = codigo
        self.mensaje = mensaje
        self.headers = headers


def respuesta_error(
    trace_id: str, status: int, codigo: str, mensaje: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"codigo": codigo, "mensaje": mensaje, "trace_id": trace_id},
        headers=headers,
    )


def _trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", "")


def registrar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return respuesta_error(_trace_id(request), exc.status, exc.codigo, exc.mensaje, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validacion(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Solo se nombran los campos: los valores recibidos pueden ser PII (ej. numero_documento).
        campos = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
        return respuesta_error(
            _trace_id(request), 400, "SOLICITUD_INVALIDA", f"Parámetros inválidos: {', '.join(campos)}"
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codigos = {404: "RUTA_NO_ENCONTRADA", 405: "METODO_NO_PERMITIDO"}
        return respuesta_error(
            _trace_id(request), exc.status_code, codigos.get(exc.status_code, "ERROR_HTTP"), str(exc.detail)
        )

    @app.exception_handler(Exception)
    async def _inesperado(request: Request, exc: Exception) -> JSONResponse:
        log.exception("error_inesperado trace_id=%s", _trace_id(request))
        return respuesta_error(
            _trace_id(request), 500, "ERROR_INTERNO", "Error interno del servicio simulado"
        )
