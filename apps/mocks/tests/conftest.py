"""Fixtures. CRM y Facturación usan los insumos de data/raw (no versionados):
si faltan, sus pruebas se omiten con un aviso. El ERP usa su contrato versionado en openapi/."""

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mocks import crm, erp, facturacion
from mocks.common.config import Settings

from .contrato import Contrato

REPO = Path(__file__).resolve().parents[3]
APIS_DIR = Path(os.getenv("MOCKS_TEST_APIS_DIR", REPO / "data" / "raw" / "04_apis"))
DATA_DIR = APIS_DIR / "datos_mock"
ERP_SPEC = Path(__file__).resolve().parents[1] / "openapi" / "erp-api.yaml"
API_KEY = "clave-de-pruebas-123"

requiere_insumos = pytest.mark.skipif(
    not (DATA_DIR / "crm_clientes.json").is_file() or not (APIS_DIR / "crm-api.yaml").is_file(),
    reason="Faltan los insumos en data/raw/04_apis: ejecute scripts/bootstrap_data.py",
)


def crear_settings(**cambios: Any) -> Settings:
    valores: dict[str, Any] = {
        "api_key": API_KEY,
        "fail_rate": 0.0,
        "rate_limit_per_min": 10_000,
        "data_dir": DATA_DIR,
        "seed": 7,
    }
    valores.update(cambios)
    return Settings(**valores)


def cliente_http(app: FastAPI, con_clave: bool = True) -> TestClient:
    return TestClient(app, headers={"X-API-Key": API_KEY} if con_clave else {})


FABRICAS: dict[str, Callable[..., FastAPI]] = {
    "crm": crm.create_app,
    "facturacion": facturacion.create_app,
    "erp": erp.create_app,
}


@pytest.fixture
def crm_http() -> TestClient:
    return cliente_http(crm.create_app(crear_settings()))


@pytest.fixture
def fac_http() -> TestClient:
    return cliente_http(facturacion.create_app(crear_settings()))


@pytest.fixture
def erp_http() -> TestClient:
    return cliente_http(erp.create_app(crear_settings()))


@pytest.fixture(scope="session")
def crm_contrato() -> Contrato:
    return Contrato(APIS_DIR / "crm-api.yaml")


@pytest.fixture(scope="session")
def fac_contrato() -> Contrato:
    return Contrato(APIS_DIR / "facturacion-api.yaml")


@pytest.fixture(scope="session")
def erp_contrato() -> Contrato:
    return Contrato(ERP_SPEC)


@pytest.fixture(scope="session")
def clientes() -> dict[str, dict[str, Any]]:
    datos = json.loads((DATA_DIR / "crm_clientes.json").read_text(encoding="utf-8"))
    return {c["cliente_id"]: c for c in datos}


@pytest.fixture(scope="session")
def facturas() -> list[dict[str, Any]]:
    return json.loads((DATA_DIR / "facturas.json").read_text(encoding="utf-8"))


def operaciones_app(app: FastAPI) -> set[tuple[str, str]]:
    """Operaciones expuestas, leídas del OpenAPI que genera FastAPI (estable entre versiones)."""
    return {
        (metodo.upper(), ruta)
        for ruta, ops in app.openapi()["paths"].items()
        if ruta.startswith("/v1")
        for metodo in ops
    }
