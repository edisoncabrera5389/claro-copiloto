"""Resiliencia del cliente HTTP: reintentos, Retry-After, circuit breaker y seguridad de los POST."""

import httpx
import pytest

from copiloto_mcp.sistemas import ErrorNegocio, SistemaNoDisponible

from .conftest import CRM


def err(status: int, codigo: str, **headers) -> httpx.Response:
    return httpx.Response(
        status, json={"codigo": codigo, "mensaje": codigo.lower(), "trace_id": "t"}, headers=headers
    )


async def test_get_exitoso_envia_api_key_y_traceparent(respx_mock, fabrica_cliente):
    ruta = respx_mock.get(f"{CRM}/clientes/C-1001").respond(200, json={"cliente_id": "C-1001"})
    c = fabrica_cliente()
    assert await c.get("/clientes/C-1001") == {"cliente_id": "C-1001"}
    req = ruta.calls.last.request
    assert req.headers["X-API-Key"] == "clave-de-pruebas-123"
    assert req.headers["traceparent"].startswith("00-")


async def test_503_se_reintenta_con_backoff_y_el_mismo_trace(respx_mock, fabrica_cliente, esperas):
    ruta = respx_mock.get(f"{CRM}/x").mock(
        side_effect=[
            err(503, "SERVICIO_NO_DISPONIBLE"),
            err(503, "SERVICIO_NO_DISPONIBLE"),
            httpx.Response(200, json=[]),
        ]
    )
    c = fabrica_cliente()
    assert await c.get("/x") == []
    assert ruta.call_count == 3
    assert esperas == [0.1, 0.2]  # base 0.1 · 2^(n-1), jitter fijo en el máximo
    assert len({call.request.headers["traceparent"] for call in ruta.calls}) == 1
    assert c.reintentos_realizados == 2


async def test_503_agota_reintentos(respx_mock, fabrica_cliente):
    respx_mock.get(f"{CRM}/x").mock(return_value=err(503, "SERVICIO_NO_DISPONIBLE"))
    with pytest.raises(SistemaNoDisponible) as e:
        await fabrica_cliente().get("/x")
    assert e.value.codigo == "SERVICIO_NO_DISPONIBLE" and e.value.sistema == "crm" and e.value.sin_efecto


def test_backoff_tiene_tope_y_jitter(fabrica_cliente):
    c = fabrica_cliente(backoff_base_s=0.5, backoff_max_s=1.5)
    assert [c._espera_backoff(n) for n in (1, 2, 3, 4)] == [0.5, 1.0, 1.5, 1.5]
    c._aleatorio = lambda: 0.0
    assert c._espera_backoff(2) == 0.5  # mitad del tope con el jitter mínimo


async def test_429_corto_respeta_retry_after(respx_mock, fabrica_cliente, esperas):
    respx_mock.get(f"{CRM}/x").mock(
        side_effect=[err(429, "LIMITE_EXCEDIDO", **{"Retry-After": "2"}), httpx.Response(200, json={})]
    )
    c = fabrica_cliente()
    assert await c.get("/x") == {}
    assert esperas == [2.0]
    assert c.breaker.fallas_consecutivas == 0  # el 429 no es una falla del sistema


async def test_429_largo_falla_rapido_sin_esperar(respx_mock, fabrica_cliente, esperas):
    ruta = respx_mock.get(f"{CRM}/x").mock(return_value=err(429, "LIMITE_EXCEDIDO", **{"Retry-After": "60"}))
    with pytest.raises(SistemaNoDisponible) as e:
        await fabrica_cliente().get("/x")
    assert e.value.codigo == "LIMITE_EXCEDIDO" and e.value.retry_after_s == 60
    assert ruta.call_count == 1 and esperas == []


@pytest.mark.parametrize(
    ("status", "codigo"), [(404, "CLIENTE_NO_ENCONTRADO"), (409, "OFERTA_RECIENTE"), (400, "X")]
)
async def test_4xx_de_negocio_no_se_reintenta(respx_mock, fabrica_cliente, status, codigo):
    ruta = respx_mock.post(f"{CRM}/x").mock(return_value=err(status, codigo))
    c = fabrica_cliente()
    with pytest.raises(ErrorNegocio) as e:
        await c.post("/x", {})
    assert e.value.codigo == codigo and e.value.status == status and ruta.call_count == 1
    assert c.breaker.fallas_consecutivas == 0


async def test_post_503_se_reintenta_porque_no_tuvo_efecto(respx_mock, fabrica_cliente):
    ruta = respx_mock.post(f"{CRM}/x").mock(side_effect=[err(503, "S"), httpx.Response(201, json={"id": 1})])
    assert await fabrica_cliente().post("/x", {}) == {"id": 1}
    assert ruta.call_count == 2


async def test_post_500_no_se_reintenta(respx_mock, fabrica_cliente):
    ruta = respx_mock.post(f"{CRM}/x").mock(return_value=err(500, "ERROR_INTERNO"))
    with pytest.raises(SistemaNoDisponible) as e:
        await fabrica_cliente().post("/x", {})
    assert ruta.call_count == 1 and not e.value.sin_efecto


async def test_post_timeout_no_se_reintenta(respx_mock, fabrica_cliente):
    ruta = respx_mock.post(f"{CRM}/x").mock(side_effect=httpx.ReadTimeout("lento"))
    with pytest.raises(SistemaNoDisponible) as e:
        await fabrica_cliente().post("/x", {})
    assert e.value.codigo == "TIMEOUT" and not e.value.sin_efecto and ruta.call_count == 1


async def test_get_timeout_si_se_reintenta(respx_mock, fabrica_cliente):
    ruta = respx_mock.get(f"{CRM}/x").mock(
        side_effect=[httpx.ReadTimeout("lento"), httpx.Response(200, json={})]
    )
    assert await fabrica_cliente().get("/x") == {}
    assert ruta.call_count == 2


async def test_error_de_conexion_se_reintenta_incluso_en_post(respx_mock, fabrica_cliente):
    ruta = respx_mock.post(f"{CRM}/x").mock(
        side_effect=[httpx.ConnectError("caído"), httpx.Response(201, json={})]
    )
    assert await fabrica_cliente().post("/x", {}) == {}
    assert ruta.call_count == 2


async def test_circuito_se_abre_y_falla_sin_llamar(respx_mock, fabrica_cliente):
    t = [0.0]
    ruta = respx_mock.get(f"{CRM}/x").mock(return_value=err(503, "S"))
    c = fabrica_cliente(reloj=lambda: t[0], breaker_fallas=5, breaker_abierto_s=30, reintentos=3)
    for _ in range(2):  # 3 + 2 intentos fallidos = 5 → abre
        with pytest.raises(SistemaNoDisponible):
            await c.get("/x")
    assert c.breaker.estado == "abierto" and ruta.call_count == 5

    with pytest.raises(SistemaNoDisponible) as e:
        await c.get("/x")
    assert e.value.codigo == "CIRCUITO_ABIERTO" and e.value.retry_after_s == 30
    assert ruta.call_count == 5  # no se llamó al sistema

    t[0] = 31  # pasa el tiempo: semiabierto, una prueba exitosa cierra
    ruta.mock(return_value=httpx.Response(200, json={"ok": True}))
    assert await c.get("/x") == {"ok": True}
    assert c.breaker.estado == "cerrado"


async def test_respuesta_sin_cuerpo(respx_mock, fabrica_cliente):
    respx_mock.post(f"{CRM}/x").respond(201)
    assert await fabrica_cliente().post("/x", {}) is None


async def test_error_sin_json(respx_mock, fabrica_cliente):
    respx_mock.get(f"{CRM}/x").respond(404, text="no")
    with pytest.raises(ErrorNegocio) as e:
        await fabrica_cliente().get("/x")
    assert e.value.codigo == "ERROR_SOLICITUD"
