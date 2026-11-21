"""ERP simulado (puerto 8083) según apps/mocks/openapi/erp-api.yaml (contrato propio del proyecto).

Lo consume n8n tras una acción confirmada: órdenes de servicio (visita técnica, envío de equipo)
y notas crédito que contabilizan los ajustes de facturación.
"""

from copy import deepcopy
from datetime import timedelta
from itertools import count
from typing import Annotated, Any, Literal

from fastapi import APIRouter, FastAPI, Query, Request
from pydantic import BaseModel, Field

from mocks.common.base import crear_app_base
from mocks.common.config import Settings
from mocks.common.errors import ApiError

# Visita técnica prioritaria en 24 h (POL-RET-2026: ≥ 3 tickets técnicos en 90 días).
DIAS_PROGRAMACION = {"prioritaria": 1, "estandar": 3}
PATRON_CLIENTE = r"^C-\d{4}$"


class NuevaOrden(BaseModel):
    cliente_id: str = Field(pattern=PATRON_CLIENTE)
    tipo: Literal["visita_tecnica", "envio_equipo", "retiro_equipo"]
    prioridad: Literal["estandar", "prioritaria"] = "estandar"
    equipo: Literal["modem", "repetidor", "decodificador"] | None = None
    ticket_id: str | None = Field(default=None, pattern=r"^TK-\d+$")
    descripcion: str | None = Field(default=None, max_length=1000)


class NuevaNotaCredito(BaseModel):
    factura_id: str = Field(pattern=r"^F-\d+$")
    cliente_id: str = Field(pattern=PATRON_CLIENTE)
    valor: int = Field(ge=1)
    motivo: str = Field(min_length=1, max_length=500)
    ajuste_id: str | None = None


class EstadoErp:
    def __init__(self) -> None:
        self.ordenes: dict[str, dict[str, Any]] = {}
        self.notas: dict[str, dict[str, Any]] = {}
        self.seq_orden = count(70001)
        self.seq_nota = count(1)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    hoy = settings.fecha_referencia
    app = crear_app_base("erp", "ERP (mock) – Claro Copiloto", settings, EstadoErp)
    router = APIRouter(prefix="/v1")

    def estado(request: Request) -> EstadoErp:
        return request.app.state.datos

    @router.post("/ordenes-servicio", operation_id="crearOrdenServicio", status_code=201)
    async def crear_orden(request: Request, body: NuevaOrden) -> dict:
        if body.tipo in ("envio_equipo", "retiro_equipo") and body.equipo is None:
            raise ApiError(400, "SOLICITUD_INVALIDA", f"El tipo {body.tipo} requiere el campo equipo")
        est = estado(request)
        orden = {
            "orden_id": f"OS-{next(est.seq_orden)}",
            "cliente_id": body.cliente_id,
            "tipo": body.tipo,
            "prioridad": body.prioridad,
            "equipo": body.equipo,
            "ticket_id": body.ticket_id,
            "estado": "programada",
            "fecha_creacion": hoy.isoformat(),
            "fecha_programada": (hoy + timedelta(days=DIAS_PROGRAMACION[body.prioridad])).isoformat(),
        }
        est.ordenes[orden["orden_id"]] = orden
        return deepcopy(orden)

    @router.get("/ordenes-servicio", operation_id="listarOrdenesServicio")
    async def listar_ordenes(
        request: Request, cliente_id: Annotated[str, Query(pattern=PATRON_CLIENTE)]
    ) -> list[dict]:
        ordenes = [o for o in estado(request).ordenes.values() if o["cliente_id"] == cliente_id]
        return deepcopy(sorted(ordenes, key=lambda o: o["orden_id"], reverse=True))

    @router.get("/ordenes-servicio/{ordenId}", operation_id="obtenerOrdenServicio")
    async def obtener_orden(request: Request, ordenId: str) -> dict:  # noqa: N803
        orden = estado(request).ordenes.get(ordenId)
        if orden is None:
            raise ApiError(404, "ORDEN_NO_ENCONTRADA", f"No existe la orden {ordenId}")
        return deepcopy(orden)

    @router.post("/notas-credito", operation_id="crearNotaCredito", status_code=201)
    async def crear_nota(request: Request, body: NuevaNotaCredito) -> dict:
        est = estado(request)
        if body.ajuste_id:
            previa = next((n for n in est.notas.values() if n["ajuste_id"] == body.ajuste_id), None)
            if previa is not None:  # evita contabilizar dos veces el mismo ajuste si n8n reintenta
                raise ApiError(
                    409,
                    "NOTA_CREDITO_DUPLICADA",
                    f"El ajuste {body.ajuste_id} ya tiene la nota {previa['nota_id']}",
                )
        nota = {
            "nota_id": f"NC-{next(est.seq_nota):05d}",
            "factura_id": body.factura_id,
            "cliente_id": body.cliente_id,
            "valor": body.valor,
            "motivo": body.motivo,
            "ajuste_id": body.ajuste_id,
            "estado": "contabilizada",
            "fecha": hoy.isoformat(),
        }
        est.notas[nota["nota_id"]] = nota
        return deepcopy(nota)

    @router.get("/notas-credito/{notaId}", operation_id="obtenerNotaCredito")
    async def obtener_nota(request: Request, notaId: str) -> dict:  # noqa: N803
        nota = estado(request).notas.get(notaId)
        if nota is None:
            raise ApiError(404, "NOTA_CREDITO_NO_ENCONTRADA", f"No existe la nota crédito {notaId}")
        return deepcopy(nota)

    app.include_router(router)
    return app
