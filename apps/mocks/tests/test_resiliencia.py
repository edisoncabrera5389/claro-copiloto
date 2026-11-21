"""Reglas transversales a los 3 servicios: API key (401), límite (429 + Retry-After), 503 simulado,
trazas, administración de la demo y logs sin PII."""

import logging

import pytest
from pydantic import ValidationError

from mocks.common.config import Settings
from mocks.common.ratelimit import RateLimiter

from .conftest import API_KEY, FABRICAS, cliente_http, crear_settings, requiere_insumos

# (servicio, fixture del contrato, ruta concreta, plantilla del contrato)
CASOS = [
    pytest.param(
        "crm", "crm_contrato", "/v1/clientes/C-1001", "/clientes/{clienteId}", marks=requiere_insumos
    ),
    pytest.param(
        "facturacion", "fac_contrato", "/v1/facturas/F-5001", "/facturas/{facturaId}", marks=requiere_insumos
    ),
    pytest.param("erp", "erp_contrato", "/v1/ordenes-servicio?cliente_id=C-1001", "/ordenes-servicio"),
]


def _app(servicio, **cambios):
    return FABRICAS[servicio](crear_settings(**cambios))


# --- Autenticación ---------------------------------------------------------------------------


@pytest.mark.parametrize(("servicio", "contrato", "ruta", "plantilla"), CASOS)
@pytest.mark.parametrize("cabeceras", [{}, {"X-API-Key": ""}, {"X-API-Key": "clave-equivocada"}])
def test_sin_api_key_valida_es_401(request, servicio, contrato, ruta, plantilla, cabeceras):
    http = cliente_http(_app(servicio), con_clave=False)
    r = http.get(ruta, headers=cabeceras)
    cuerpo = request.getfixturevalue(contrato).validar("GET", plantilla, r)
    assert r.status_code == 401 and cuerpo["codigo"] == "NO_AUTORIZADO" and cuerpo["trace_id"]


@pytest.mark.parametrize("servicio", ["erp"])
@pytest.mark.parametrize("ruta", ["/health", "/openapi.json", "/docs"])
def test_rutas_publicas_sin_api_key(servicio, ruta):
    assert cliente_http(_app(servicio), con_clave=False).get(ruta).status_code == 200


# --- Límite de solicitudes (429) -------------------------------------------------------------


@pytest.mark.parametrize(("servicio", "contrato", "ruta", "plantilla"), CASOS)
def test_supera_limite_por_minuto_es_429_con_retry_after(request, servicio, contrato, ruta, plantilla):
    http = cliente_http(_app(servicio, rate_limit_per_min=3))
    restantes = [http.get(ruta).headers["X-RateLimit-Remaining"] for _ in range(3)]
    assert restantes == ["2", "1", "0"]

    r = http.get(ruta)
    cuerpo = request.getfixturevalue(contrato).validar("GET", plantilla, r)
    assert r.status_code == 429 and cuerpo["codigo"] == "LIMITE_EXCEDIDO"
    assert 1 <= int(r.headers["Retry-After"]) <= 60


def test_limite_por_defecto_es_60_por_minuto():
    http = cliente_http(
        FABRICAS["erp"](
            crear_settings(rate_limit_per_min=Settings.model_fields["rate_limit_per_min"].default)
        )
    )
    codigos = [http.get("/v1/ordenes-servicio?cliente_id=C-1001").status_code for _ in range(61)]
    assert codigos[:60] == [200] * 60 and codigos[60] == 429


def test_solicitudes_sin_clave_no_consumen_cupo():
    app = _app("erp", rate_limit_per_min=1)
    sin_clave = cliente_http(app, con_clave=False)
    for _ in range(5):
        assert sin_clave.get("/v1/ordenes-servicio?cliente_id=C-1001").status_code == 401
    assert cliente_http(app).get("/v1/ordenes-servicio?cliente_id=C-1001").status_code == 200


def test_ventana_deslizante_y_retry_after():
    t = [0.0]
    limiter = RateLimiter(2, ventana_s=60, reloj=lambda: t[0])
    assert limiter.consumir("k")[0] and limiter.consumir("k")[0]
    t[0] = 10.0
    assert limiter.consumir("k") == (False, 50, 0)
    assert limiter.consumir("otra-clave")[0]  # el cupo es por clave
    t[0] = 60.5
    assert limiter.consumir("k") == (True, 0, 1)


# --- Falla simulada (503) --------------------------------------------------------------------


@pytest.mark.parametrize(("servicio", "contrato", "ruta", "plantilla"), CASOS)
def test_fail_rate_1_siempre_503(request, servicio, contrato, ruta, plantilla):
    r = cliente_http(_app(servicio, fail_rate=1.0)).get(ruta)
    cuerpo = request.getfixturevalue(contrato).validar("GET", plantilla, r)
    assert r.status_code == 503 and cuerpo["codigo"] == "SERVICIO_NO_DISPONIBLE"


def test_fail_rate_por_defecto_es_2_por_ciento():
    assert Settings(api_key=API_KEY).fail_rate == 0.02
    http = cliente_http(_app("erp", fail_rate=0.02, seed=2026))
    n = 3000
    fallas = sum(http.get("/v1/ordenes-servicio?cliente_id=C-1001").status_code == 503 for _ in range(n))
    assert 0.01 <= fallas / n <= 0.035, fallas


def test_503_ocurre_antes_del_handler_y_no_tiene_efecto():
    app = _app("erp", fail_rate=1.0)
    http = cliente_http(app)
    r = http.post("/v1/ordenes-servicio", json={"cliente_id": "C-1001", "tipo": "visita_tecnica"})
    assert r.status_code == 503
    app.state.fail_rate = 0.0
    assert http.get("/v1/ordenes-servicio?cliente_id=C-1001").json() == []


def test_429_tiene_prioridad_sobre_503():
    http = cliente_http(_app("erp", fail_rate=1.0, rate_limit_per_min=1))
    assert http.get("/health").status_code == 200
    assert http.get("/v1/ordenes-servicio?cliente_id=C-1001").status_code == 503
    assert http.get("/v1/ordenes-servicio?cliente_id=C-1001").status_code == 429


# --- Administración para la demo -------------------------------------------------------------


def test_admin_cambia_fail_rate_y_limite_en_caliente():
    http = cliente_http(_app("erp"))
    assert http.get("/_admin/config").json() == {"fail_rate": 0.0, "rate_limit_per_min": 10_000}
    r = http.put("/_admin/config", json={"fail_rate": 1.0, "rate_limit_per_min": 5})
    assert r.json() == {"fail_rate": 1.0, "rate_limit_per_min": 5}
    assert http.get("/v1/ordenes-servicio?cliente_id=C-1001").status_code == 503
    # /_admin queda exento del 503 y del límite para poder revertir
    assert http.put("/_admin/config", json={"fail_rate": 0.0}).status_code == 200
    assert http.get("/v1/ordenes-servicio?cliente_id=C-1001").status_code == 200


def test_admin_requiere_api_key_y_valida_rangos():
    app = _app("erp")
    assert cliente_http(app, con_clave=False).get("/_admin/config").status_code == 401
    assert cliente_http(app).put("/_admin/config", json={"fail_rate": 1.5}).status_code == 400


def test_admin_reset_recarga_estado():
    http = cliente_http(_app("erp"))
    http.post("/v1/ordenes-servicio", json={"cliente_id": "C-1001", "tipo": "visita_tecnica"})
    assert http.post("/_admin/reset").json() == {"estado": "reiniciado"}
    assert http.get("/v1/ordenes-servicio?cliente_id=C-1001").json() == []


def test_admin_no_aparece_en_openapi():
    rutas = cliente_http(_app("erp")).get("/openapi.json").json()["paths"]
    assert not [r for r in rutas if r.startswith("/_admin") or r == "/health"]


# --- Errores genéricos, trazas y configuración -----------------------------------------------


def test_ruta_y_metodo_desconocidos_usan_esquema_de_error(erp_http, erp_contrato):
    erp_contrato.validar_error(erp_http.get("/v1/no-existe"), "RUTA_NO_ENCONTRADA")
    erp_contrato.validar_error(erp_http.delete("/v1/ordenes-servicio"), "METODO_NO_PERMITIDO")


def test_trace_id_se_propaga_desde_traceparent(erp_http):
    trace = "4bf92f3577b34da6a3ce929d0e0e4736"
    r = erp_http.get("/v1/ordenes-servicio/OS-1", headers={"traceparent": f"00-{trace}-00f067aa0ba902b7-01"})
    assert r.headers["X-Trace-Id"] == trace and r.json()["trace_id"] == trace


def test_trace_id_generado_si_no_llega(erp_http):
    r = erp_http.get("/v1/ordenes-servicio/OS-1")
    assert len(r.headers["X-Trace-Id"]) == 32 and r.json()["trace_id"] == r.headers["X-Trace-Id"]


@pytest.mark.parametrize(
    "cambios", [{"api_key": "corta"}, {"fail_rate": 1.5}, {"fail_rate": -0.1}, {"rate_limit_per_min": 0}]
)
def test_configuracion_invalida_no_arranca(cambios):
    with pytest.raises(ValidationError):
        crear_settings(**cambios)


def test_api_key_obligatoria(monkeypatch):
    monkeypatch.delenv("MOCKS_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_sin_datos_falla_con_mensaje_claro(tmp_path):
    with pytest.raises(RuntimeError, match="bootstrap_data"):
        FABRICAS["crm"](crear_settings(data_dir=tmp_path))


# --- PII en logs (Ley 1581) ------------------------------------------------------------------


@requiere_insumos
def test_logs_no_contienen_documento_ni_query_string(crm_http, clientes, caplog):
    c = clientes["C-1001"]
    caplog.set_level(logging.INFO, logger="mocks.http")
    crm_http.get("/v1/clientes", params={"tipo_documento": "CC", "numero_documento": c["numero_documento"]})
    crm_http.get("/v1/clientes", params={"tipo_documento": "XX", "numero_documento": c["numero_documento"]})
    crm_http.get("/v1/clientes/C-1001")
    texto = caplog.text
    assert '"ruta": "/v1/clientes"' in texto
    for dato in (c["numero_documento"], c["celular"], c["email"], "numero_documento="):
        assert dato not in texto


def test_health_exitoso_no_se_registra(erp_http, caplog):
    caplog.set_level(logging.INFO, logger="mocks.http")
    assert erp_http.get("/health").status_code == 200
    erp_http.get("/v1/ordenes-servicio/OS-1")
    assert '"ruta": "/health"' not in caplog.text
    assert '"ruta": "/v1/ordenes-servicio/OS-1"' in caplog.text


@requiere_insumos
def test_error_400_no_devuelve_el_valor_recibido(crm_http, clientes):
    doc = clientes["C-1001"]["numero_documento"]
    r = crm_http.get("/v1/clientes", params={"tipo_documento": "XX", "numero_documento": doc})
    assert r.status_code == 400 and doc not in r.text
