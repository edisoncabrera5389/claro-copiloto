"""Contrato del ERP (openapi/erp-api.yaml, versionado en el repo: no requiere insumos)."""

import pytest

from mocks import erp

from .conftest import crear_settings, operaciones_app


def test_implementa_todas_las_operaciones_del_contrato(erp_contrato):
    faltantes = erp_contrato.operaciones() - operaciones_app(erp.create_app(crear_settings()))
    assert not faltantes, f"Operaciones del contrato sin implementar: {faltantes}"


@pytest.mark.parametrize(("prioridad", "fecha"), [("prioritaria", "2026-11-19"), ("estandar", "2026-11-21")])
def test_crear_visita_tecnica_programada_segun_prioridad(erp_http, erp_contrato, prioridad, fecha):
    cuerpo = {
        "cliente_id": "C-1013",
        "tipo": "visita_tecnica",
        "prioridad": prioridad,
        "ticket_id": "TK-990001",
    }
    r = erp_http.post("/v1/ordenes-servicio", json=cuerpo)
    orden = erp_contrato.validar("POST", "/ordenes-servicio", r)
    assert r.status_code == 201
    assert orden["estado"] == "programada" and orden["fecha_programada"] == fecha


def test_envio_de_equipo_requiere_equipo(erp_http, erp_contrato):
    r = erp_http.post("/v1/ordenes-servicio", json={"cliente_id": "C-1002", "tipo": "envio_equipo"})
    assert erp_contrato.validar("POST", "/ordenes-servicio", r)["codigo"] == "SOLICITUD_INVALIDA"
    r = erp_http.post(
        "/v1/ordenes-servicio", json={"cliente_id": "C-1002", "tipo": "envio_equipo", "equipo": "repetidor"}
    )
    assert erp_contrato.validar("POST", "/ordenes-servicio", r)["equipo"] == "repetidor"


@pytest.mark.parametrize(
    "cuerpo",
    [{"cliente_id": "1002", "tipo": "visita_tecnica"}, {"cliente_id": "C-1002", "tipo": "otro"}],
)
def test_orden_invalida(erp_http, erp_contrato, cuerpo):
    r = erp_http.post("/v1/ordenes-servicio", json=cuerpo)
    assert erp_contrato.validar("POST", "/ordenes-servicio", r)["codigo"] == "SOLICITUD_INVALIDA"


def test_listar_y_obtener_ordenes(erp_http, erp_contrato):
    ids = [
        erp_http.post("/v1/ordenes-servicio", json={"cliente_id": "C-1001", "tipo": "visita_tecnica"}).json()[
            "orden_id"
        ]
        for _ in range(2)
    ]
    erp_http.post("/v1/ordenes-servicio", json={"cliente_id": "C-1002", "tipo": "visita_tecnica"})
    r = erp_http.get("/v1/ordenes-servicio", params={"cliente_id": "C-1001"})
    assert [o["orden_id"] for o in erp_contrato.validar("GET", "/ordenes-servicio", r)] == ids[::-1]

    r = erp_http.get(f"/v1/ordenes-servicio/{ids[0]}")
    assert erp_contrato.validar("GET", "/ordenes-servicio/{ordenId}", r)["orden_id"] == ids[0]
    r = erp_http.get("/v1/ordenes-servicio/OS-1")
    assert erp_contrato.validar("GET", "/ordenes-servicio/{ordenId}", r)["codigo"] == "ORDEN_NO_ENCONTRADA"


def test_listar_ordenes_requiere_cliente_valido(erp_http, erp_contrato):
    r = erp_http.get("/v1/ordenes-servicio")
    assert erp_contrato.validar("GET", "/ordenes-servicio", r)["codigo"] == "SOLICITUD_INVALIDA"


NOTA = {
    "factura_id": "F-5003",
    "cliente_id": "C-1001",
    "valor": 50_000,
    "motivo": "Ajuste",
    "ajuste_id": "AJ-0001",
}


def test_nota_credito_y_duplicado_por_ajuste(erp_http, erp_contrato):
    r = erp_http.post("/v1/notas-credito", json=NOTA)
    nota = erp_contrato.validar("POST", "/notas-credito", r)
    assert r.status_code == 201 and nota["estado"] == "contabilizada"

    r = erp_http.get(f"/v1/notas-credito/{nota['nota_id']}")
    assert erp_contrato.validar("GET", "/notas-credito/{notaId}", r) == nota

    r = erp_http.post("/v1/notas-credito", json=NOTA)
    assert erp_contrato.validar("POST", "/notas-credito", r)["codigo"] == "NOTA_CREDITO_DUPLICADA"
    assert r.status_code == 409


def test_nota_credito_sin_ajuste_permite_varias(erp_http):
    sin_ajuste = {**NOTA, "ajuste_id": None}
    assert erp_http.post("/v1/notas-credito", json=sin_ajuste).status_code == 201
    assert erp_http.post("/v1/notas-credito", json=sin_ajuste).status_code == 201


def test_nota_credito_invalida_e_inexistente(erp_http, erp_contrato):
    r = erp_http.post("/v1/notas-credito", json={**NOTA, "valor": 0})
    assert erp_contrato.validar("POST", "/notas-credito", r)["codigo"] == "SOLICITUD_INVALIDA"
    r = erp_http.get("/v1/notas-credito/NC-99999")
    assert erp_contrato.validar("GET", "/notas-credito/{notaId}", r)["codigo"] == "NOTA_CREDITO_NO_ENCONTRADA"
