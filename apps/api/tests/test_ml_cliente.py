"""Cliente del ml-service: respuesta normal y degradación (nunca lanza)."""

import httpx

from copiloto_api.ml_cliente import ClienteML


def cliente(manejador) -> ClienteML:
    http = httpx.AsyncClient(base_url="http://ml", transport=httpx.MockTransport(manejador))
    return ClienteML("http://ml", cliente=http)


async def test_intencion_y_churn_ok():
    def manejador(r: httpx.Request) -> httpx.Response:
        if r.url.path == "/intencion":
            return httpx.Response(200, json={"intencion": "facturacion", "confianza": 0.9})
        return httpx.Response(200, json={"nivel": "medio", "probabilidad": 0.3})

    c = cliente(manejador)
    assert (await c.intencion("cobro doble"))["intencion"] == "facturacion"
    assert (await c.churn({"cliente_id": "C-1001"}))["nivel"] == "medio"


async def test_error_o_caida_devuelve_none():
    def caido(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin conexión")

    assert await cliente(caido).intencion("x") is None
    assert await cliente(lambda r: httpx.Response(503)).churn({}) is None
