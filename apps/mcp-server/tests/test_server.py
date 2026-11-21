"""Servidor MCP por protocolo (cliente en memoria) con CRM y Facturación simulados con respx."""

import json
import logging

import httpx
import pytest
from fastmcp import Client
from starlette.testclient import TestClient

from .conftest import CRM, FAC
from .datos import CEL, DOC, MAIL, factura, ficha, servicio, ticket


async def llamar(mcp, tool: str, **args):
    async with Client(mcp) as c:
        return await c.call_tool(tool, args, raise_on_error=False)


def texto(r) -> str:
    return " ".join(getattr(b, "text", "") for b in r.content)


def mock_evaluacion(respx_mock, f=None, tickets=(), facturas=None, cliente="C-2001"):
    respx_mock.get(f"{CRM}/clientes/{cliente}").respond(200, json=f or ficha(cliente))
    respx_mock.get(f"{CRM}/clientes/{cliente}/tickets").respond(200, json=list(tickets))
    respx_mock.get(f"{FAC}/clientes/{cliente}/facturas").respond(200, json=facturas or [factura()])


# --- Catálogo de tools -----------------------------------------------------------------------


async def test_catalogo_de_tools_y_anotaciones(entorno):
    async with Client(entorno.mcp) as c:
        tools = {t.name: t for t in await c.list_tools()}
    lectura = {
        "buscarCliente",
        "obtenerCliente",
        "listarServicios",
        "listarTickets",
        "listarFacturas",
        "obtenerSaldo",
        "obtenerFactura",
        "evaluarRetencion",
    }
    escritura = {"crearTicket", "registrarOfertaRetencion", "aplicarAjuste"}
    assert set(tools) == lectura | escritura
    assert all(tools[n].annotations.read_only_hint for n in lectura)
    assert not any(tools[n].annotations.read_only_hint for n in escritura)
    assert all("token_confirmacion" in tools[n].input_schema["properties"] for n in escritura)
    assert not any("token" in str(tools[n].input_schema) for n in lectura)


# --- Lectura y PII ---------------------------------------------------------------------------


async def test_obtener_cliente_filtra_pii(entorno, respx_mock):
    respx_mock.get(f"{CRM}/clientes/C-2001").respond(200, json=ficha())
    r = await llamar(entorno.mcp, "obtenerCliente", cliente_id="C-2001")
    assert not r.is_error and r.data["cliente_id"] == "C-2001"
    assert not {"numero_documento", "celular", "email"} & set(r.data)
    crudo = json.dumps(r.structured_content) + texto(r)
    assert DOC not in crudo and CEL not in crudo and MAIL not in crudo


async def test_buscar_cliente(entorno, respx_mock):
    ruta = respx_mock.get(f"{CRM}/clientes").respond(
        200, json={"cliente_id": "C-2001", "nombre": "X", "estado": "activo"}
    )
    r = await llamar(entorno.mcp, "buscarCliente", tipo_documento="CC", numero_documento=DOC)
    assert r.data == {"cliente_id": "C-2001", "nombre": "X", "estado": "activo"}
    assert dict(ruta.calls.last.request.url.params) == {"tipo_documento": "CC", "numero_documento": DOC}


@pytest.mark.parametrize(
    ("tool", "args", "url", "params"),
    [
        ("listarServicios", {"cliente_id": "C-2001"}, f"{CRM}/clientes/C-2001/servicios", {}),
        (
            "listarTickets",
            {"cliente_id": "C-2001", "dias": 30},
            f"{CRM}/clientes/C-2001/tickets",
            {"dias": "30"},
        ),
        ("listarFacturas", {"cliente_id": "C-2001"}, f"{FAC}/clientes/C-2001/facturas", {"limite": "3"}),
        ("obtenerSaldo", {"cliente_id": "C-2001"}, f"{FAC}/clientes/C-2001/saldo", {}),
        ("obtenerFactura", {"factura_id": "F-5003"}, f"{FAC}/facturas/F-5003", {}),
    ],
)
async def test_tools_de_lectura_llaman_al_sistema_correcto(entorno, respx_mock, tool, args, url, params):
    ruta = respx_mock.get(url).respond(200, json=[{"ok": 1}] if tool.startswith("listar") else {"ok": 1})
    r = await llamar(entorno.mcp, tool, **args)
    assert not r.is_error and ruta.called
    assert dict(ruta.calls.last.request.url.params) == params


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("obtenerCliente", {"cliente_id": "1004"}),
        ("listarTickets", {"cliente_id": "C-2001", "dias": 400}),
        ("listarFacturas", {"cliente_id": "C-2001", "limite": 13}),
        ("obtenerFactura", {"factura_id": "X"}),
    ],
)
async def test_validacion_de_entrada_sin_llamar_al_sistema(entorno, respx_mock, tool, args):
    r = await llamar(entorno.mcp, tool, **args)
    assert r.is_error and not respx_mock.calls


async def test_error_de_negocio_del_sistema_llega_como_tool_error(entorno, respx_mock):
    respx_mock.get(f"{CRM}/clientes/C-9999").respond(
        404, json={"codigo": "CLIENTE_NO_ENCONTRADO", "mensaje": "No existe"}
    )
    r = await llamar(entorno.mcp, "obtenerCliente", cliente_id="C-9999")
    assert r.is_error and texto(r).startswith("CLIENTE_NO_ENCONTRADO: No existe (sistema=crm)")


async def test_sistema_caido_informa_y_abre_circuito(entorno, respx_mock):
    respx_mock.get(f"{CRM}/clientes/C-2001").respond(
        503, json={"codigo": "SERVICIO_NO_DISPONIBLE", "mensaje": "x"}
    )
    r1 = await llamar(entorno.mcp, "obtenerCliente", cliente_id="C-2001")
    r2 = await llamar(entorno.mcp, "obtenerCliente", cliente_id="C-2001")
    r3 = await llamar(entorno.mcp, "obtenerCliente", cliente_id="C-2001")
    assert "SERVICIO_NO_DISPONIBLE" in texto(r1) and "sistema=crm" in texto(r1)
    assert texto(r3).startswith("CIRCUITO_ABIERTO") and "reintentar_en_s=" in texto(r3)
    assert r2.is_error and entorno.crm.breaker.estado == "abierto"


# --- Skill evaluarRetencion ------------------------------------------------------------------


async def test_evaluar_retencion_por_mcp(entorno, respx_mock):
    mock_evaluacion(respx_mock)
    r = await llamar(entorno.mcp, "evaluarRetencion", cliente_id="C-2001")
    assert r.data["elegible"] and r.data["tramo"] == "mas_de_24" and r.data["advertencias"] == []
    assert DOC not in json.dumps(r.structured_content)


async def test_evaluar_retencion_tolera_facturacion_caida(entorno, respx_mock):
    respx_mock.get(f"{CRM}/clientes/C-2001").respond(200, json=ficha())
    respx_mock.get(f"{CRM}/clientes/C-2001/tickets").respond(200, json=[])
    respx_mock.get(f"{FAC}/clientes/C-2001/facturas").respond(503, json={"codigo": "SERVICIO_NO_DISPONIBLE"})
    r = await llamar(entorno.mcp, "evaluarRetencion", cliente_id="C-2001")
    assert r.data["elegible"] and "Facturación no respondió" in r.data["advertencias"][0]


async def test_evaluar_retencion_requiere_crm(entorno, respx_mock):
    respx_mock.get(f"{CRM}/clientes/C-2001").respond(
        404, json={"codigo": "CLIENTE_NO_ENCONTRADO", "mensaje": "x"}
    )
    respx_mock.get(f"{CRM}/clientes/C-2001/tickets").respond(200, json=[])
    respx_mock.get(f"{FAC}/clientes/C-2001/facturas").respond(200, json=[])
    r = await llamar(entorno.mcp, "evaluarRetencion", cliente_id="C-2001")
    assert r.is_error and "CLIENTE_NO_ENCONTRADO" in texto(r)


async def test_evaluar_retencion_servicio_inexistente(entorno, respx_mock):
    mock_evaluacion(respx_mock)
    r = await llamar(entorno.mcp, "evaluarRetencion", cliente_id="C-2001", servicio_id="S9")
    assert texto(r).startswith("SERVICIO_NO_ENCONTRADO")


# --- Escritura: propuesta, token y ejecución -------------------------------------------------

TICKET = {
    "cliente_id": "C-2001",
    "categoria": "soporte_tecnico",
    "descripcion": "Visita prioritaria. Cliente CC 1023456789, cel 300 123 4567",
    "prioridad": "prioritaria",
    "escalar_a": "nivel2",
}


async def test_sin_token_devuelve_propuesta_y_no_ejecuta(entorno, respx_mock):
    post = respx_mock.post(f"{CRM}/clientes/C-2001/tickets").respond(201, json={"ticket_id": "TK-1"})
    r = await llamar(entorno.mcp, "crearTicket", **TICKET)
    assert not r.is_error and r.data["estado"] == "requiere_confirmacion"
    assert r.data["parametros"]["descripcion"] == "Visita prioritaria. Cliente CC [DOCUMENTO], cel [CELULAR]"
    assert r.data["requiere_rol"] == "asesor" and len(r.data["huella"]) == 64
    assert not post.called


async def test_con_token_valido_ejecuta_una_sola_vez(entorno, respx_mock):
    post = respx_mock.post(f"{CRM}/clientes/C-2001/tickets").respond(201, json={"ticket_id": "TK-1"})
    propuesta = (await llamar(entorno.mcp, "crearTicket", **TICKET)).data
    token = entorno.conf.emitir("crearTicket", propuesta["parametros"], "A-001")

    r = await llamar(entorno.mcp, "crearTicket", **TICKET, token_confirmacion=token)
    assert r.data["estado"] == "ejecutada" and r.data["confirmada_por"] == "A-001"
    assert r.data["resultado"] == {"ticket_id": "TK-1"}
    cuerpo = json.loads(post.calls.last.request.content)
    assert cuerpo == {k: v for k, v in propuesta["parametros"].items() if k != "cliente_id"}
    assert "1023456789" not in post.calls.last.request.content.decode()

    r2 = await llamar(entorno.mcp, "crearTicket", **TICKET, token_confirmacion=token)
    assert texto(r2).startswith("CONFIRMACION_YA_USADA") and post.call_count == 1


async def test_token_de_otros_parametros_o_falso_no_ejecuta(entorno, respx_mock):
    post = respx_mock.post(f"{CRM}/clientes/C-2001/tickets").respond(201, json={})
    propuesta = (await llamar(entorno.mcp, "crearTicket", **TICKET)).data
    token = entorno.conf.emitir("crearTicket", propuesta["parametros"], "A-001")
    r = await llamar(
        entorno.mcp, "crearTicket", **{**TICKET, "escalar_a": "supervisor"}, token_confirmacion=token
    )
    assert texto(r).startswith("CONFIRMACION_NO_COINCIDE")
    r = await llamar(entorno.mcp, "crearTicket", **TICKET, token_confirmacion="inventado.por-el-llm")
    assert texto(r).startswith("CONFIRMACION_INVALIDA")
    assert not post.called


async def test_si_el_sistema_no_aplico_la_escritura_el_token_se_puede_reusar(entorno, respx_mock):
    post = respx_mock.post(f"{CRM}/clientes/C-2001/tickets").mock(
        side_effect=[httpx.Response(503, json={"codigo": "S"})] * 3
        + [httpx.Response(201, json={"ticket_id": "TK-2"})]
    )
    propuesta = (await llamar(entorno.mcp, "crearTicket", **TICKET)).data
    token = entorno.conf.emitir("crearTicket", propuesta["parametros"], "A-001")
    r1 = await llamar(entorno.mcp, "crearTicket", **TICKET, token_confirmacion=token)
    assert r1.is_error and "sistema=crm" in texto(r1)
    r2 = await llamar(entorno.mcp, "crearTicket", **TICKET, token_confirmacion=token)
    assert r2.data["estado"] == "ejecutada" and post.call_count == 4


async def test_error_de_negocio_consume_el_token(entorno, respx_mock):
    respx_mock.post(f"{CRM}/clientes/C-2001/tickets").respond(404, json={"codigo": "CLIENTE_NO_ENCONTRADO"})
    propuesta = (await llamar(entorno.mcp, "crearTicket", **TICKET)).data
    token = entorno.conf.emitir("crearTicket", propuesta["parametros"], "A-001")
    assert "CLIENTE_NO_ENCONTRADO" in texto(
        await llamar(entorno.mcp, "crearTicket", **TICKET, token_confirmacion=token)
    )
    assert "YA_USADA" in texto(await llamar(entorno.mcp, "crearTicket", **TICKET, token_confirmacion=token))


# --- registrarOfertaRetencion ----------------------------------------------------------------


async def test_oferta_no_elegible_ni_propone(entorno, respx_mock):
    mock_evaluacion(respx_mock, ficha(mora=45))
    r = await llamar(entorno.mcp, "registrarOfertaRetencion", cliente_id="C-2001", codigo="RET-A")
    assert texto(r).startswith("CLIENTE_NO_ELEGIBLE") and "45 días de mora" in texto(r)


async def test_oferta_bloqueada_por_visita_pendiente(entorno, respx_mock):
    mock_evaluacion(respx_mock, tickets=[ticket(1), ticket(2), ticket(3)])
    r = await llamar(entorno.mcp, "registrarOfertaRetencion", cliente_id="C-2001", codigo="RET-A")
    assert texto(r).startswith("OFERTA_NO_DISPONIBLE") and "visita" in texto(r)


async def test_oferta_que_no_aplica_al_servicio(entorno, respx_mock):
    mock_evaluacion(respx_mock, ficha(servicios=[servicio("movil", "Claro Max 25 GB", 49_900, 6)]))
    r = await llamar(entorno.mcp, "registrarOfertaRetencion", cliente_id="C-2001", codigo="RET-A")
    assert texto(r).startswith("OFERTA_NO_APLICA")


async def test_oferta_con_varios_servicios_exige_servicio_id(entorno, respx_mock):
    dos = [
        servicio("hogar", "Hogar Fibra 300", 89_900, 30, "S1"),
        servicio("movil", "Claro Max 60 GB", 59_415, 30, "S2"),
    ]
    mock_evaluacion(respx_mock, ficha(servicios=dos))
    r = await llamar(entorno.mcp, "registrarOfertaRetencion", cliente_id="C-2001", codigo="RET-A")
    assert texto(r).startswith("SERVICIO_REQUERIDO") and "S1, S2" in texto(r)
    r = await llamar(
        entorno.mcp, "registrarOfertaRetencion", cliente_id="C-2001", codigo="RET-A", servicio_id="S2"
    )
    assert r.data["parametros"]["servicio_id"] == "S2"


async def test_oferta_flujo_completo_con_descripcion_de_la_politica(entorno, respx_mock):
    mock_evaluacion(respx_mock)
    post = respx_mock.post(f"{CRM}/clientes/C-2001/ofertas-retencion").respond(
        201, json={"oferta_id": "OR-1"}
    )
    propuesta = (
        await llamar(entorno.mcp, "registrarOfertaRetencion", cliente_id="C-2001", codigo="RET-B")
    ).data
    assert propuesta["parametros"]["descripcion"].startswith(
        "Upgrade al siguiente plan: Hogar Fibra 300 → Hogar Fibra 500"
    )

    token = entorno.conf.emitir("registrarOfertaRetencion", propuesta["parametros"], "A-007")
    r = await llamar(
        entorno.mcp, "registrarOfertaRetencion", cliente_id="C-2001", codigo="RET-B", token_confirmacion=token
    )
    assert r.data["estado"] == "ejecutada"
    cuerpo = json.loads(post.calls.last.request.content)
    assert cuerpo == {
        "codigo": "RET-B",
        "descripcion": propuesta["parametros"]["descripcion"],
        "asesor_id": "A-007",
    }


# --- aplicarAjuste (> $50.000 requiere supervisor) -------------------------------------------


async def test_ajuste_mayor_a_50000_requiere_supervisor(entorno, respx_mock):
    post = respx_mock.post(f"{FAC}/facturas/F-5003/ajustes").respond(201, json={"ajuste_id": "AJ-1"})
    args = {"factura_id": "F-5003", "valor": 80_000, "motivo": "Cobro no reconocido"}
    propuesta = (await llamar(entorno.mcp, "aplicarAjuste", **args)).data
    assert propuesta["requiere_rol"] == "supervisor" and "$80.000" in propuesta["resumen"]

    del_asesor = entorno.conf.emitir("aplicarAjuste", propuesta["parametros"], "A-001")
    r = await llamar(entorno.mcp, "aplicarAjuste", **args, token_confirmacion=del_asesor)
    assert texto(r).startswith("AJUSTE_REQUIERE_APROBACION") and not post.called

    del_supervisor = entorno.conf.emitir(
        "aplicarAjuste", propuesta["parametros"], "SUP-007", rol="supervisor"
    )
    r = await llamar(entorno.mcp, "aplicarAjuste", **args, token_confirmacion=del_supervisor)
    assert r.data["estado"] == "ejecutada" and r.data["rol"] == "supervisor"
    assert json.loads(post.calls.last.request.content)["aprobado_por"] == "SUP-007"


async def test_ajuste_hasta_50000_lo_confirma_el_asesor(entorno, respx_mock):
    post = respx_mock.post(f"{FAC}/facturas/F-5003/ajustes").respond(201, json={})
    args = {"factura_id": "F-5003", "valor": 50_000, "motivo": "Falla. Contacto: ana@correo.co"}
    propuesta = (await llamar(entorno.mcp, "aplicarAjuste", **args)).data
    assert propuesta["requiere_rol"] == "asesor" and "[CORREO]" in propuesta["parametros"]["motivo"]
    token = entorno.conf.emitir("aplicarAjuste", propuesta["parametros"], "A-001")
    r = await llamar(entorno.mcp, "aplicarAjuste", **args, token_confirmacion=token)
    assert r.data["estado"] == "ejecutada"
    assert json.loads(post.calls.last.request.content)["aprobado_por"] is None


# --- Operación -------------------------------------------------------------------------------


def test_health_expone_estado_de_los_circuitos(entorno):
    with TestClient(entorno.mcp.http_app()) as tc:
        r = tc.get("/health").json()
    assert r["estado"] == "ok" and r["sistemas"]["crm"]["estado"] == "cerrado"
    assert set(r["sistemas"]) == {"crm", "facturacion"}


async def test_logs_sin_argumentos_ni_pii(entorno, respx_mock, caplog):
    caplog.set_level(logging.INFO, logger="copiloto_mcp")
    respx_mock.get(f"{CRM}/clientes").respond(
        200, json={"cliente_id": "C-2001", "nombre": "X", "estado": "activo"}
    )
    await llamar(entorno.mcp, "buscarCliente", tipo_documento="CC", numero_documento=DOC)
    await llamar(entorno.mcp, "crearTicket", **TICKET)
    assert '"tool": "buscarCliente"' in caplog.text and '"estado": "requiere_confirmacion"' in caplog.text
    assert DOC not in caplog.text and "1023456789" not in caplog.text
