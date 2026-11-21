"""Integración contra los mocks levantados con docker compose (datos reales de la prueba).

    docker compose up -d crm-mock facturacion-mock
    uv run pytest -m integracion

Se omite si los mocks no responden. Verifica los casos del golden dataset que usan tools (GQ-25 a
GQ-28) y el flujo completo de confirmación. Al terminar reinicia los datos de los mocks.
"""

import os
import urllib.request
from pathlib import Path

import pytest
from fastmcp import Client

from copiloto_mcp.confirmacion import Confirmaciones
from copiloto_mcp.server import crear_servidor
from copiloto_mcp.sistemas import ClienteSistema

from .conftest import SECRETO, crear_settings

pytestmark = pytest.mark.integracion

RAIZ = Path(__file__).resolve().parents[3]
CRM_URL = os.getenv("MCP_IT_CRM_URL", "http://127.0.0.1:8081/v1")
FAC_URL = os.getenv("MCP_IT_FACTURACION_URL", "http://127.0.0.1:8082/v1")


def _api_key() -> str:
    if os.getenv("MOCKS_API_KEY"):
        return os.environ["MOCKS_API_KEY"]
    env = RAIZ / ".env"
    for linea in env.read_text(encoding="utf-8").splitlines() if env.is_file() else []:
        if linea.strip().startswith("MOCKS_API_KEY="):
            return linea.split("=", 1)[1].strip().strip("'\"")
    return ""


def _mocks_arriba() -> bool:
    try:
        for base in (CRM_URL, FAC_URL):
            with urllib.request.urlopen(base.removesuffix("/v1") + "/health", timeout=1):  # noqa: S310
                pass
        return bool(_api_key())
    except OSError:
        return False


if not _mocks_arriba():
    pytest.skip("Mocks no disponibles (docker compose up -d) o falta MOCKS_API_KEY", allow_module_level=True)


def _reset() -> None:
    for base in (CRM_URL, FAC_URL):
        req = urllib.request.Request(  # noqa: S310
            base.removesuffix("/v1") + "/_admin/reset", method="POST", headers={"X-API-Key": _api_key()}
        )
        urllib.request.urlopen(req, timeout=3).close()  # noqa: S310


@pytest.fixture
def mcp_real():
    _reset()
    s = crear_settings(crm_url=CRM_URL, facturacion_url=FAC_URL, mocks_api_key=_api_key())
    conf = Confirmaciones(SECRETO, 300)
    crm, fac = ClienteSistema("crm", CRM_URL, s), ClienteSistema("facturacion", FAC_URL, s)
    yield crear_servidor(s, crm=crm, facturacion=fac, confirmaciones=conf), conf
    _reset()


async def llamar(mcp, tool, **args):
    async with Client(mcp) as c:
        return (await c.call_tool(tool, args)).data


async def test_gq25_plan_y_saldo_de_c1001(mcp_real):
    mcp, _ = mcp_real
    ficha = await llamar(mcp, "obtenerCliente", cliente_id="C-1001")
    saldo = await llamar(mcp, "obtenerSaldo", cliente_id="C-1001")
    planes = {s["plan"]: s["valor_mensual"] for s in ficha["servicios"]}
    assert planes == {"Hogar Fibra 500": 109_900, "Claro Max 60 GB": 59_415}
    assert saldo["saldo_pendiente"] == 169_315 and saldo["proxima_fecha_limite"] == "2026-11-25"
    assert not {"numero_documento", "celular", "email"} & set(ficha)


async def test_gq26_c1004_elegible_30_meses_con_upgrade_a_fibra500(mcp_real):
    mcp, _ = mcp_real
    r = await llamar(mcp, "evaluarRetencion", cliente_id="C-1004")
    o = {x["codigo"]: x for x in r["servicios"][0]["ofertas"]}
    assert r["elegible"] and r["antiguedad_meses"] == 30 and r["tramo"] == "mas_de_24"
    assert (
        o["RET-A"]["porcentaje"] == 30
        and o["RET-A"]["meses"] == 6
        and o["RET-A"]["valor_descuento_mensual"] == 26_970
    )
    assert o["RET-B"]["plan_destino"] == "Hogar Fibra 500"


async def test_gq27_c1007_no_elegible_por_mora(mcp_real):
    mcp, _ = mcp_real
    r = await llamar(mcp, "evaluarRetencion", cliente_id="C-1007")
    assert not r["elegible"] and r["motivos_no_elegible"][0]["codigo"] == "MORA_MAYOR_30_DIAS"
    assert "45 días" in r["motivos_no_elegible"][0]["detalle"]


async def test_gq28_c1013_visita_prioritaria_y_flujo_confirmado(mcp_real):
    """Evalúa → propone visita → asesor confirma → se crea → el descuento queda disponible → oferta."""
    mcp, conf = mcp_real
    r = await llamar(mcp, "evaluarRetencion", cliente_id="C-1013")
    assert (
        r["visita_tecnica_prioritaria"]["requerida"]
        and r["visita_tecnica_prioritaria"]["tickets_tecnicos_90d"] == 4
    )
    assert r["antiguedad_meses"] == 26
    assert not {x["codigo"]: x for x in r["servicios"][0]["ofertas"]}["RET-A"]["disponible"]

    args = {
        "cliente_id": "C-1013",
        "categoria": "soporte_tecnico",
        "descripcion": "Visita técnica prioritaria 24 h",
        "prioridad": "prioritaria",
        "escalar_a": "nivel2",
    }
    propuesta = await llamar(mcp, "crearTicket", **args)
    assert propuesta["estado"] == "requiere_confirmacion"
    token = conf.emitir("crearTicket", propuesta["parametros"], "A-001")
    creado = await llamar(mcp, "crearTicket", **args, token_confirmacion=token)
    assert creado["estado"] == "ejecutada" and creado["resultado"]["prioridad"] == "prioritaria"

    r = await llamar(mcp, "evaluarRetencion", cliente_id="C-1013")
    assert r["visita_tecnica_prioritaria"]["agendada"]
    assert {x["codigo"]: x for x in r["servicios"][0]["ofertas"]}["RET-A"]["disponible"]

    propuesta = await llamar(mcp, "registrarOfertaRetencion", cliente_id="C-1013", codigo="RET-A")
    token = conf.emitir("registrarOfertaRetencion", propuesta["parametros"], "A-001")
    registrada = await llamar(
        mcp, "registrarOfertaRetencion", cliente_id="C-1013", codigo="RET-A", token_confirmacion=token
    )
    assert registrada["resultado"]["codigo"] == "RET-A" and registrada["resultado"]["asesor_id"] == "A-001"

    r = await llamar(mcp, "evaluarRetencion", cliente_id="C-1013")  # ya no es elegible: 1 oferta / 12 meses
    assert not r["elegible"] and r["motivos_no_elegible"][0]["codigo"] == "OFERTA_ULTIMOS_12_MESES"


async def test_ajuste_80000_exige_supervisor_contra_facturacion_real(mcp_real):
    mcp, conf = mcp_real
    args = {"factura_id": "F-5003", "valor": 80_000, "motivo": "Cobro no reconocido"}
    propuesta = await llamar(mcp, "aplicarAjuste", **args)
    token = conf.emitir("aplicarAjuste", propuesta["parametros"], "SUP-001", rol="supervisor")
    r = await llamar(mcp, "aplicarAjuste", **args, token_confirmacion=token)
    assert r["resultado"]["aprobado_por"] == "SUP-001"


async def test_antiguedad_calculada_coincide_con_el_crm_en_los_20_clientes(mcp_real):
    from copiloto_mcp.retencion import antiguedad_meses

    mcp, _ = mcp_real
    s = crear_settings()
    for n in range(1001, 1021):
        ficha = await llamar(mcp, "obtenerCliente", cliente_id=f"C-{n}")
        assert antiguedad_meses(ficha["servicios"], s.fecha_referencia)[0] == ficha["antiguedad_meses"], (
            ficha["cliente_id"]
        )
