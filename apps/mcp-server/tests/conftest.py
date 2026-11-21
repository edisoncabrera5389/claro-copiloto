from collections.abc import Callable
from dataclasses import dataclass, field

import pytest
from fastmcp import FastMCP

from copiloto_mcp.config import Settings
from copiloto_mcp.confirmacion import Confirmaciones
from copiloto_mcp.server import crear_servidor
from copiloto_mcp.sistemas import ClienteSistema

CRM = "http://crm.test/v1"
FAC = "http://fac.test/v1"
SECRETO = "secreto-de-pruebas-con-mas-de-32-caracteres"


def crear_settings(**cambios) -> Settings:
    valores = {
        "crm_url": CRM,
        "facturacion_url": FAC,
        "mocks_api_key": "clave-de-pruebas-123",
        "confirmacion_secret": SECRETO,
        "backoff_base_s": 0.1,
        "backoff_max_s": 1.0,
    }
    valores.update(cambios)
    return Settings(**valores)


@dataclass
class Entorno:
    mcp: FastMCP
    crm: ClienteSistema
    fac: ClienteSistema
    conf: Confirmaciones
    esperas: list[float] = field(default_factory=list)


@pytest.fixture
def esperas() -> list[float]:
    return []


@pytest.fixture
def fabrica_cliente(esperas) -> Callable[..., ClienteSistema]:
    """ClienteSistema con sueño simulado (registra las esperas) y jitter fijo."""

    def crear(nombre: str = "crm", base: str = CRM, reloj=None, **cambios) -> ClienteSistema:
        async def dormir(s: float) -> None:
            esperas.append(s)

        extra = {"reloj": reloj} if reloj else {}
        return ClienteSistema(
            nombre, base, crear_settings(**cambios), dormir=dormir, aleatorio=lambda: 1.0, **extra
        )

    return crear


@pytest.fixture
def entorno(fabrica_cliente, esperas) -> Entorno:
    s = crear_settings()
    crm = fabrica_cliente("crm", CRM)
    fac = fabrica_cliente("facturacion", FAC)
    conf = Confirmaciones(SECRETO, 300)
    return Entorno(crear_servidor(s, crm=crm, facturacion=fac, confirmaciones=conf), crm, fac, conf, esperas)
