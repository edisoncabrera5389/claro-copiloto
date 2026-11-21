"""Contrato y reglas de negocio del CRM (crm-api.yaml)."""

import pytest

from mocks import crm

from .conftest import crear_settings, operaciones_app, requiere_insumos

pytestmark = requiere_insumos


def test_implementa_todas_las_operaciones_del_contrato(crm_contrato):
    app = crm.create_app(crear_settings())
    faltantes = crm_contrato.operaciones() - operaciones_app(app)
    assert not faltantes, f"Operaciones del contrato sin implementar: {faltantes}"


# --- GET /clientes ---------------------------------------------------------------------------


def test_buscar_cliente_devuelve_resumen_sin_pii(crm_http, crm_contrato, clientes):
    c = clientes["C-1001"]
    r = crm_http.get(
        "/v1/clientes",
        params={"tipo_documento": c["tipo_documento"], "numero_documento": c["numero_documento"]},
    )
    cuerpo = crm_contrato.validar("GET", "/clientes", r)
    assert cuerpo == {"cliente_id": "C-1001", "nombre": c["nombre"], "estado": c["estado"]}


def test_buscar_cliente_tolera_puntos_en_documento(crm_http, clientes):
    c = clientes["C-1002"]
    n = c["numero_documento"]
    con_puntos = f"{n[:-6]}.{n[-6:-3]}.{n[-3:]}"
    r = crm_http.get("/v1/clientes", params={"tipo_documento": "CC", "numero_documento": con_puntos})
    assert r.status_code == 200 and r.json()["cliente_id"] == "C-1002"


def test_buscar_cliente_no_encontrado_no_repite_el_documento(crm_http, crm_contrato):
    r = crm_http.get("/v1/clientes", params={"tipo_documento": "CC", "numero_documento": "99887766"})
    cuerpo = crm_contrato.validar("GET", "/clientes", r)
    assert r.status_code == 404 and cuerpo["codigo"] == "CLIENTE_NO_ENCONTRADO"
    assert "99887766" not in r.text


@pytest.mark.parametrize(
    "params", [{"tipo_documento": "XX", "numero_documento": "1"}, {"tipo_documento": "CC"}]
)
def test_buscar_cliente_parametros_invalidos(crm_http, crm_contrato, params):
    r = crm_http.get("/v1/clientes", params=params)
    assert r.status_code == 400
    crm_contrato.validar_error(r, "SOLICITUD_INVALIDA")


# --- GET /clientes/{id} y /servicios ---------------------------------------------------------


def test_obtener_cliente_ficha_completa(crm_http, crm_contrato):
    r = crm_http.get("/v1/clientes/C-1004")
    cuerpo = crm_contrato.validar("GET", "/clientes/{clienteId}", r)
    assert r.status_code == 200 and cuerpo["cliente_id"] == "C-1004"


def test_todas_las_fichas_cumplen_el_contrato(crm_http, crm_contrato, clientes):
    for cliente_id in clientes:
        crm_contrato.validar("GET", "/clientes/{clienteId}", crm_http.get(f"/v1/clientes/{cliente_id}"))


def test_obtener_cliente_inexistente(crm_http, crm_contrato):
    r = crm_http.get("/v1/clientes/C-9999")
    assert crm_contrato.validar("GET", "/clientes/{clienteId}", r)["codigo"] == "CLIENTE_NO_ENCONTRADO"
    assert r.status_code == 404


@pytest.mark.parametrize("cliente_id", ["C-12", "X-1001", "C-10010"])
def test_cliente_id_fuera_del_patron(crm_http, crm_contrato, cliente_id):
    r = crm_http.get(f"/v1/clientes/{cliente_id}")
    assert r.status_code == 400
    crm_contrato.validar_error(r, "SOLICITUD_INVALIDA")


def test_listar_servicios_activos(crm_http, crm_contrato, clientes):
    r = crm_http.get("/v1/clientes/C-1001/servicios")
    cuerpo = crm_contrato.validar("GET", "/clientes/{clienteId}/servicios", r)
    assert [s["servicio_id"] for s in cuerpo] == [s["servicio_id"] for s in clientes["C-1001"]["servicios"]]
    assert all(s["estado"] == "activo" for s in cuerpo)


# --- Tickets ---------------------------------------------------------------------------------


def test_tickets_ventana_por_defecto_90_dias_ordenados(crm_http, crm_contrato):
    # Referencia 2026-11-18: C-1013 tiene 4 tickets técnicos entre sep y nov.
    r = crm_http.get("/v1/clientes/C-1013/tickets")
    cuerpo = crm_contrato.validar("GET", "/clientes/{clienteId}/tickets", r)
    fechas = [t["fecha"] for t in cuerpo]
    assert fechas == ["2026-11-13", "2026-10-30", "2026-10-08", "2026-09-09"]


def test_tickets_ventana_30_dias(crm_http):
    r = crm_http.get("/v1/clientes/C-1013/tickets", params={"dias": 30})
    assert [t["fecha"] for t in r.json()] == ["2026-11-13", "2026-10-30"]


@pytest.mark.parametrize("dias", [0, 366, -5])
def test_tickets_ventana_fuera_de_rango(crm_http, crm_contrato, dias):
    r = crm_http.get("/v1/clientes/C-1013/tickets", params={"dias": dias})
    assert r.status_code == 400
    crm_contrato.validar_error(r, "SOLICITUD_INVALIDA")


def test_crear_ticket_y_consultarlo(crm_http, crm_contrato):
    nuevo = {
        "categoria": "soporte_tecnico",
        "descripcion": "Visita técnica prioritaria por intermitencia",
        "prioridad": "prioritaria",
        "escalar_a": "nivel2",
    }
    r = crm_http.post("/v1/clientes/C-1013/tickets", json=nuevo)
    ticket = crm_contrato.validar("POST", "/clientes/{clienteId}/tickets", r)
    assert r.status_code == 201
    assert ticket["estado"] == "abierto" and ticket["fecha"] == "2026-11-18"
    assert ticket["prioridad"] == "prioritaria" and ticket["escalar_a"] == "nivel2"
    assert "descripcion" not in ticket  # texto libre: no se devuelve

    listados = crm_http.get("/v1/clientes/C-1013/tickets").json()
    assert listados[0]["ticket_id"] == ticket["ticket_id"]
    ficha = crm_http.get("/v1/clientes/C-1013").json()
    assert ficha["tickets_recientes"][0]["ticket_id"] == ticket["ticket_id"]


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"categoria": "otra", "descripcion": "x"},
        {"categoria": "facturacion"},
        {"categoria": "facturacion", "descripcion": "x" * 1001},
        {"categoria": "facturacion", "descripcion": "x", "escalar_a": "gerente"},
    ],
)
def test_crear_ticket_invalido(crm_http, crm_contrato, cuerpo):
    r = crm_http.post("/v1/clientes/C-1001/tickets", json=cuerpo)
    assert crm_contrato.validar("POST", "/clientes/{clienteId}/tickets", r)["codigo"] == "SOLICITUD_INVALIDA"


def test_crear_ticket_cliente_inexistente(crm_http, crm_contrato):
    r = crm_http.post("/v1/clientes/C-9999/tickets", json={"categoria": "facturacion", "descripcion": "x"})
    assert r.status_code == 404
    crm_contrato.validar_error(r, "CLIENTE_NO_ENCONTRADO")


# --- Ofertas de retención (409 de negocio) ---------------------------------------------------

OFERTA = {"codigo": "RET-A", "descripcion": "30 % de descuento por 6 meses", "asesor_id": "A-001"}


def test_registrar_oferta_y_bloquear_segunda_en_12_meses(crm_http, crm_contrato):
    r = crm_http.post("/v1/clientes/C-1004/ofertas-retencion", json=OFERTA)
    crm_contrato.validar("POST", "/clientes/{clienteId}/ofertas-retencion", r)
    assert r.status_code == 201
    assert r.json()["codigo"] == "RET-A" and r.json()["fecha"] == "2026-11-18"

    ficha = crm_contrato.validar("GET", "/clientes/{clienteId}", crm_http.get("/v1/clientes/C-1004"))
    assert ficha["ofertas_retencion_12m"][0]["codigo"] == "RET-A"

    r2 = crm_http.post("/v1/clientes/C-1004/ofertas-retencion", json={**OFERTA, "codigo": "RET-B"})
    cuerpo = crm_contrato.validar("POST", "/clientes/{clienteId}/ofertas-retencion", r2)
    assert r2.status_code == 409 and cuerpo["codigo"] == "OFERTA_RECIENTE"


def test_oferta_rechazada_por_mora_mayor_a_30_dias(crm_http, crm_contrato, clientes):
    assert clientes["C-1003"]["dias_mora"] > 30
    r = crm_http.post("/v1/clientes/C-1003/ofertas-retencion", json=OFERTA)
    cuerpo = crm_contrato.validar("POST", "/clientes/{clienteId}/ofertas-retencion", r)
    assert r.status_code == 409 and cuerpo["codigo"] == "CLIENTE_EN_MORA"
    # El 409 no deja rastro
    assert crm_http.get("/v1/clientes/C-1003").json()["ofertas_retencion_12m"] == []


def test_oferta_anterior_a_12_meses_no_bloquea(crm_http):
    est = crm_http.app.state.datos
    est.clientes["C-1005"]["ofertas_retencion_12m"].append(
        {"codigo": "RET-B", "descripcion": "upgrade", "fecha": "2025-11-18"}
    )
    r = crm_http.post("/v1/clientes/C-1005/ofertas-retencion", json=OFERTA)
    assert r.status_code == 201


def test_oferta_codigo_fuera_del_enum(crm_http, crm_contrato):
    r = crm_http.post("/v1/clientes/C-1004/ofertas-retencion", json={**OFERTA, "codigo": "RET-C"})
    assert r.status_code == 400
    crm_contrato.validar_error(r, "SOLICITUD_INVALIDA")
