"""CRM simulado (puerto 8081) según data/raw/04_apis/crm-api.yaml."""

import re
from copy import deepcopy
from datetime import date, timedelta
from itertools import count
from typing import Annotated, Any, Literal

from fastapi import APIRouter, FastAPI, Path, Query, Request
from pydantic import BaseModel, Field

from mocks.common.base import crear_app_base
from mocks.common.config import Settings
from mocks.common.datos import cargar_json, hace_un_anio
from mocks.common.errors import ApiError

MORA_MAXIMA_DIAS = 30  # POL-RET-2026: sin mora > 30 días

Categoria = Literal["soporte_tecnico", "facturacion", "consulta_planes", "cancelacion", "portabilidad"]
ClienteId = Annotated[str, Path(pattern=r"^C-\d{4}$", examples=["C-1001"])]


class NuevoTicket(BaseModel):
    categoria: Categoria
    descripcion: str = Field(min_length=1, max_length=1000)
    prioridad: Literal["estandar", "prioritaria"] = "estandar"
    escalar_a: Literal["nivel2", "supervisor", "mesa_retencion"] | None = None


class OfertaRetencion(BaseModel):
    codigo: Literal["RET-A", "RET-B"]
    descripcion: str = Field(min_length=1)
    fecha: date | None = Field(default=None, description="Ignorada: la fecha de registro la asigna el CRM")
    asesor_id: str | None = None


class EstadoCrm:
    """Estado en memoria. Los POST lo modifican; /_admin/reset lo recarga."""

    def __init__(self, clientes: list[dict[str, Any]], hoy: date):
        self.clientes = {c["cliente_id"]: c for c in deepcopy(clientes)}
        self.hoy = hoy
        self.seq_ticket = count(990001)
        self.seq_oferta = count(1)
        # La descripción se guarda aparte y no se devuelve: es texto libre que puede contener PII.
        self.descripciones: dict[str, str] = {}

    def cliente(self, cliente_id: str) -> dict[str, Any]:
        cliente = self.clientes.get(cliente_id)
        if cliente is None:
            raise ApiError(404, "CLIENTE_NO_ENCONTRADO", f"No existe el cliente {cliente_id}")
        return cliente


def _normalizar_documento(numero: str) -> str:
    return re.sub(r"[.\s-]", "", numero)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    def cargar() -> EstadoCrm:
        return EstadoCrm(cargar_json(settings.data_dir, "crm_clientes.json"), settings.fecha_referencia)

    app = crear_app_base("crm", "CRM Clientes (mock) – Claro Copiloto", settings, cargar)
    router = APIRouter(prefix="/v1")

    def estado(request: Request) -> EstadoCrm:
        return request.app.state.datos

    @router.get("/clientes", operation_id="buscarCliente", summary="Buscar cliente por documento")
    async def buscar_cliente(
        request: Request,
        tipo_documento: Literal["CC", "CE", "NIT", "PAS"],
        numero_documento: Annotated[str, Query(min_length=1, max_length=20)],
    ) -> dict:
        buscado = _normalizar_documento(numero_documento)
        for c in estado(request).clientes.values():
            if c["tipo_documento"] == tipo_documento and c["numero_documento"] == buscado:
                return {"cliente_id": c["cliente_id"], "nombre": c["nombre"], "estado": c["estado"]}
        # El mensaje no repite el documento consultado (PII).
        raise ApiError(404, "CLIENTE_NO_ENCONTRADO", "No existe un cliente con ese documento")

    @router.get("/clientes/{clienteId}", operation_id="obtenerCliente", summary="Obtener ficha del cliente")
    async def obtener_cliente(request: Request, clienteId: ClienteId) -> dict:  # noqa: N803
        return deepcopy(estado(request).cliente(clienteId))

    @router.get(
        "/clientes/{clienteId}/servicios", operation_id="listarServicios", summary="Listar servicios activos"
    )
    async def listar_servicios(request: Request, clienteId: ClienteId) -> list[dict]:  # noqa: N803
        servicios = estado(request).cliente(clienteId)["servicios"]
        return [deepcopy(s) for s in servicios if s["estado"] == "activo"]

    @router.get("/clientes/{clienteId}/tickets", operation_id="listarTickets", summary="Listar tickets")
    async def listar_tickets(
        request: Request,
        clienteId: ClienteId,  # noqa: N803
        dias: Annotated[int, Query(ge=1, le=365, description="Ventana de días hacia atrás")] = 90,
    ) -> list[dict]:
        est = estado(request)
        desde = est.hoy - timedelta(days=dias)
        tickets = [
            t for t in est.cliente(clienteId)["tickets_recientes"] if date.fromisoformat(t["fecha"]) >= desde
        ]
        return sorted(deepcopy(tickets), key=lambda t: t["fecha"], reverse=True)

    @router.post(
        "/clientes/{clienteId}/tickets", operation_id="crearTicket", status_code=201, summary="Crear ticket"
    )
    async def crear_ticket(request: Request, clienteId: ClienteId, body: NuevoTicket) -> dict:  # noqa: N803
        est = estado(request)
        cliente = est.cliente(clienteId)
        ticket = {
            "ticket_id": f"TK-{next(est.seq_ticket)}",
            "fecha": est.hoy.isoformat(),
            "categoria": body.categoria,
            "estado": "abierto",
            "prioridad": body.prioridad,
            "escalar_a": body.escalar_a,
        }
        est.descripciones[ticket["ticket_id"]] = body.descripcion
        cliente["tickets_recientes"].insert(0, ticket)
        return deepcopy(ticket)

    @router.post(
        "/clientes/{clienteId}/ofertas-retencion",
        operation_id="registrarOfertaRetencion",
        status_code=201,
        summary="Registrar oferta de retención aceptada",
    )
    async def registrar_oferta(request: Request, clienteId: ClienteId, body: OfertaRetencion) -> dict:  # noqa: N803
        est = estado(request)
        cliente = est.cliente(clienteId)
        if cliente["estado"] == "retirado":
            raise ApiError(409, "CLIENTE_RETIRADO", "El cliente está retirado: no aplica oferta de retención")
        if cliente["dias_mora"] > MORA_MAXIMA_DIAS:
            raise ApiError(
                409,
                "CLIENTE_EN_MORA",
                f"Cliente no elegible: {cliente['dias_mora']} días de mora (máximo {MORA_MAXIMA_DIAS})",
            )
        limite = hace_un_anio(est.hoy)
        recientes = [o for o in cliente["ofertas_retencion_12m"] if date.fromisoformat(o["fecha"]) > limite]
        if recientes:
            raise ApiError(
                409,
                "OFERTA_RECIENTE",
                f"Cliente no elegible: ya recibió la oferta {recientes[0]['codigo']} el "
                f"{recientes[0]['fecha']} (máximo 1 cada 12 meses)",
            )
        oferta: dict[str, Any] = {
            "oferta_id": f"OR-{next(est.seq_oferta):04d}",
            "codigo": body.codigo,
            "descripcion": body.descripcion,
            "fecha": est.hoy.isoformat(),
        }
        if body.asesor_id:
            oferta["asesor_id"] = body.asesor_id
        cliente["ofertas_retencion_12m"].insert(0, oferta)
        return {"cliente_id": clienteId, **deepcopy(oferta)}

    app.include_router(router)
    return app
