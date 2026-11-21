"""Facturación simulada (puerto 8082) según data/raw/04_apis/facturacion-api.yaml."""

from collections import defaultdict
from copy import deepcopy
from datetime import date
from itertools import count
from typing import Annotated, Any

from fastapi import APIRouter, FastAPI, Query, Request
from pydantic import BaseModel, Field

from mocks.common.base import crear_app_base
from mocks.common.config import Settings
from mocks.common.datos import cargar_json
from mocks.common.errors import ApiError

LIMITE_AJUSTE_NIVEL1 = 50_000  # Ajustes mayores requieren aprobado_por (supervisor)


class Ajuste(BaseModel):
    valor: int = Field(ge=1)
    motivo: str = Field(min_length=1, max_length=500)
    aprobado_por: str | None = None


class EstadoFacturacion:
    def __init__(self, facturas: list[dict[str, Any]], hoy: date):
        self.hoy = hoy
        self.facturas: dict[str, dict[str, Any]] = {}
        self.por_cliente: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for f in deepcopy(facturas):
            f["ajustes"] = []  # extensión del mock: ajustes aplicados a la factura
            self.facturas[f["factura_id"]] = f
            self.por_cliente[f["cliente_id"]].append(f)
        self.seq_ajuste = count(1)

    def de_cliente(self, cliente_id: str) -> list[dict[str, Any]]:
        if cliente_id not in self.por_cliente:
            raise ApiError(404, "CLIENTE_NO_ENCONTRADO", f"No hay facturación para el cliente {cliente_id}")
        return self.por_cliente[cliente_id]

    def factura(self, factura_id: str) -> dict[str, Any]:
        factura = self.facturas.get(factura_id)
        if factura is None:
            raise ApiError(404, "FACTURA_NO_ENCONTRADA", f"No existe la factura {factura_id}")
        return factura


def saldo_factura(f: dict[str, Any]) -> int:
    if f["estado"] == "pagada":
        return 0
    return max(0, f["valor_total"] - sum(a["valor"] for a in f["ajustes"]))


def _pesos(valor: int) -> str:
    return "$" + f"{valor:,}".replace(",", ".")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    def cargar() -> EstadoFacturacion:
        return EstadoFacturacion(cargar_json(settings.data_dir, "facturas.json"), settings.fecha_referencia)

    app = crear_app_base("facturacion", "Facturación (mock) – Claro Copiloto", settings, cargar)
    router = APIRouter(prefix="/v1")

    def estado(request: Request) -> EstadoFacturacion:
        return request.app.state.datos

    @router.get("/clientes/{clienteId}/facturas", operation_id="listarFacturas", summary="Listar facturas")
    async def listar_facturas(
        request: Request,
        clienteId: str,  # noqa: N803
        limite: Annotated[int, Query(ge=1, le=12)] = 3,
    ) -> list[dict]:
        facturas = sorted(estado(request).de_cliente(clienteId), key=lambda f: f["periodo"], reverse=True)
        return deepcopy(facturas[:limite])

    @router.get("/clientes/{clienteId}/saldo", operation_id="obtenerSaldo", summary="Saldo pendiente")
    async def obtener_saldo(request: Request, clienteId: str) -> dict:  # noqa: N803
        facturas = estado(request).de_cliente(clienteId)
        pendientes = [f for f in facturas if f["estado"] == "pendiente" and saldo_factura(f) > 0]
        return {
            "cliente_id": clienteId,
            # Total por pagar (pendiente + vencido), descontando ajustes aplicados.
            "saldo_pendiente": sum(saldo_factura(f) for f in facturas),
            "saldo_vencido": sum(saldo_factura(f) for f in facturas if f["estado"] == "vencida"),
            "proxima_fecha_limite": min((f["fecha_limite_pago"] for f in pendientes), default=None),
        }

    @router.get("/facturas/{facturaId}", operation_id="obtenerFactura", summary="Detalle de una factura")
    async def obtener_factura(request: Request, facturaId: str) -> dict:  # noqa: N803
        return deepcopy(estado(request).factura(facturaId))

    @router.post(
        "/facturas/{facturaId}/ajustes",
        operation_id="aplicarAjuste",
        status_code=201,
        summary="Aplicar ajuste a una factura",
    )
    async def aplicar_ajuste(request: Request, facturaId: str, body: Ajuste) -> dict:  # noqa: N803
        est = estado(request)
        factura = est.factura(facturaId)
        aprobado_por = (body.aprobado_por or "").strip() or None
        if body.valor > LIMITE_AJUSTE_NIVEL1 and aprobado_por is None:
            raise ApiError(
                403,
                "AJUSTE_REQUIERE_APROBACION",
                f"Ajustes mayores a {_pesos(LIMITE_AJUSTE_NIVEL1)} requieren aprobación de un supervisor "
                "(campo aprobado_por)",
            )
        ajuste = {
            "ajuste_id": f"AJ-{next(est.seq_ajuste):04d}",
            "factura_id": facturaId,
            "valor": body.valor,
            "motivo": body.motivo,
            "aprobado_por": aprobado_por,
            "fecha": est.hoy.isoformat(),
        }
        factura["ajustes"].append(ajuste)
        return {**deepcopy(ajuste), "saldo_factura": saldo_factura(factura)}

    app.include_router(router)
    return app
