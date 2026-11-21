"""Contrato y reglas de negocio de Facturación (facturacion-api.yaml)."""

import pytest

from mocks import facturacion

from .conftest import crear_settings, operaciones_app, requiere_insumos

pytestmark = requiere_insumos


def test_implementa_todas_las_operaciones_del_contrato(fac_contrato):
    app = facturacion.create_app(crear_settings())
    faltantes = fac_contrato.operaciones() - operaciones_app(app)
    assert not faltantes, f"Operaciones del contrato sin implementar: {faltantes}"


# --- Facturas --------------------------------------------------------------------------------


def test_listar_facturas_por_defecto_3_mas_recientes_primero(fac_http, fac_contrato):
    r = fac_http.get("/v1/clientes/C-1001/facturas")
    cuerpo = fac_contrato.validar("GET", "/clientes/{clienteId}/facturas", r)
    periodos = [f["periodo"] for f in cuerpo]
    assert len(cuerpo) == 3 and periodos == sorted(periodos, reverse=True)


def test_listar_facturas_limite_1(fac_http, facturas):
    r = fac_http.get("/v1/clientes/C-1001/facturas", params={"limite": 1})
    ultimo = max(f["periodo"] for f in facturas if f["cliente_id"] == "C-1001")
    assert [f["periodo"] for f in r.json()] == [ultimo]


@pytest.mark.parametrize("limite", [0, 13])
def test_listar_facturas_limite_fuera_de_rango(fac_http, fac_contrato, limite):
    r = fac_http.get("/v1/clientes/C-1001/facturas", params={"limite": limite})
    assert r.status_code == 400
    fac_contrato.validar_error(r, "SOLICITUD_INVALIDA")


def test_listar_facturas_cliente_inexistente(fac_http, fac_contrato):
    r = fac_http.get("/v1/clientes/C-9999/facturas")
    assert (
        fac_contrato.validar("GET", "/clientes/{clienteId}/facturas", r)["codigo"] == "CLIENTE_NO_ENCONTRADO"
    )


def test_todas_las_facturas_cumplen_el_contrato(fac_http, fac_contrato, facturas):
    for f in facturas:
        cuerpo = fac_contrato.validar(
            "GET", "/facturas/{facturaId}", fac_http.get(f"/v1/facturas/{f['factura_id']}")
        )
        assert cuerpo["valor_total"] == f["valor_total"]


def test_factura_inexistente(fac_http, fac_contrato):
    r = fac_http.get("/v1/facturas/F-0000")
    assert fac_contrato.validar("GET", "/facturas/{facturaId}", r)["codigo"] == "FACTURA_NO_ENCONTRADA"


# --- Saldo -----------------------------------------------------------------------------------


def test_saldo_coincide_con_facturas_pendientes_y_vencidas(fac_http, fac_contrato, facturas):
    for cliente_id in sorted({f["cliente_id"] for f in facturas}):
        propias = [f for f in facturas if f["cliente_id"] == cliente_id]
        r = fac_http.get(f"/v1/clientes/{cliente_id}/saldo")
        saldo = fac_contrato.validar("GET", "/clientes/{clienteId}/saldo", r)
        assert saldo["saldo_pendiente"] == sum(f["valor_total"] for f in propias if f["estado"] != "pagada")
        assert saldo["saldo_vencido"] == sum(f["valor_total"] for f in propias if f["estado"] == "vencida")
        limites = [f["fecha_limite_pago"] for f in propias if f["estado"] == "pendiente"]
        assert saldo["proxima_fecha_limite"] == (min(limites) if limites else None)


def test_saldo_cliente_inexistente(fac_http, fac_contrato):
    r = fac_http.get("/v1/clientes/C-9999/saldo")
    assert fac_contrato.validar("GET", "/clientes/{clienteId}/saldo", r)["codigo"] == "CLIENTE_NO_ENCONTRADO"


# --- Ajustes (403 de negocio) ----------------------------------------------------------------


def _factura_pendiente(facturas, cliente_id="C-1001"):
    return next(f for f in facturas if f["cliente_id"] == cliente_id and f["estado"] == "pendiente")


def test_ajuste_hasta_50000_sin_aprobacion_reduce_el_saldo(fac_http, fac_contrato, facturas):
    f = _factura_pendiente(facturas)
    antes = fac_http.get("/v1/clientes/C-1001/saldo").json()["saldo_pendiente"]
    r = fac_http.post(
        f"/v1/facturas/{f['factura_id']}/ajustes", json={"valor": 50_000, "motivo": "Falla 3 días"}
    )
    fac_contrato.validar("POST", "/facturas/{facturaId}/ajustes", r)
    assert r.status_code == 201 and r.json()["aprobado_por"] is None
    assert r.json()["saldo_factura"] == f["valor_total"] - 50_000
    assert fac_http.get("/v1/clientes/C-1001/saldo").json()["saldo_pendiente"] == antes - 50_000
    assert fac_http.get(f"/v1/facturas/{f['factura_id']}").json()["ajustes"][0]["valor"] == 50_000


@pytest.mark.parametrize("aprobado_por", [None, "", "   "])
def test_ajuste_mayor_a_50000_sin_aprobacion_es_403(fac_http, fac_contrato, facturas, aprobado_por):
    f = _factura_pendiente(facturas)
    cuerpo = {"valor": 50_001, "motivo": "Compensación", "aprobado_por": aprobado_por}
    r = fac_http.post(f"/v1/facturas/{f['factura_id']}/ajustes", json=cuerpo)
    error = fac_contrato.validar("POST", "/facturas/{facturaId}/ajustes", r)
    assert r.status_code == 403 and error["codigo"] == "AJUSTE_REQUIERE_APROBACION"
    # El 403 no tiene efecto
    assert fac_http.get(f"/v1/facturas/{f['factura_id']}").json()["ajustes"] == []


def test_ajuste_mayor_a_50000_con_aprobacion(fac_http, fac_contrato, facturas):
    f = _factura_pendiente(facturas)
    cuerpo = {"valor": 80_000, "motivo": "Compensación", "aprobado_por": "SUP-007"}
    r = fac_http.post(f"/v1/facturas/{f['factura_id']}/ajustes", json=cuerpo)
    fac_contrato.validar("POST", "/facturas/{facturaId}/ajustes", r)
    assert r.status_code == 201 and r.json()["aprobado_por"] == "SUP-007"


@pytest.mark.parametrize(
    "cuerpo", [{"valor": 0, "motivo": "x"}, {"valor": 1000}, {"valor": 10.5, "motivo": "x"}]
)
def test_ajuste_invalido(fac_http, fac_contrato, facturas, cuerpo):
    f = _factura_pendiente(facturas)
    r = fac_http.post(f"/v1/facturas/{f['factura_id']}/ajustes", json=cuerpo)
    assert r.status_code == 400
    fac_contrato.validar_error(r, "SOLICITUD_INVALIDA")


def test_ajuste_factura_inexistente(fac_http, fac_contrato):
    r = fac_http.post("/v1/facturas/F-0000/ajustes", json={"valor": 1000, "motivo": "x"})
    assert r.status_code == 404
    fac_contrato.validar_error(r, "FACTURA_NO_ENCONTRADA")
