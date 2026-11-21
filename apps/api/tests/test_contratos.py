"""Contratos entre servicios: la API comparte código con la ingesta (tokenizador BM25) y con el MCP
(firma de tokens). Si una copia diverge, la búsqueda híbrida o la confirmación se rompen en silencio."""

import importlib.util
from pathlib import Path

import pytest

from copiloto_api import confirmacion, dispersos

APPS = Path(__file__).resolve().parents[2]


def cargar(ruta: Path, nombre: str):
    if not ruta.is_file():
        pytest.skip(f"No está {ruta} (monorepo incompleto)")
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_tokenizador_bm25_identico_al_de_la_ingesta():
    original = APPS / "ingestion" / "src" / "ingesta" / "dispersos.py"
    ingesta = cargar(original, "dispersos_ingesta")
    assert Path(dispersos.__file__).read_bytes() == original.read_bytes()
    for texto in [
        "La luz LOS en rojo: error E-202",
        "RET-A por $109.900 (POL-RET-2026)",
        "Facturación facturas E202",
    ]:
        assert dispersos.vector_consulta(texto) == ingesta.vector_consulta(texto)
    assert dispersos.NOMBRE == ingesta.NOMBRE == "bm25-codigos-v1"


def test_token_de_la_api_lo_acepta_el_mcp():
    original = APPS / "mcp-server" / "src" / "copiloto_mcp" / "confirmacion.py"
    mcp = cargar(original, "confirmacion_mcp")
    assert Path(confirmacion.__file__).read_bytes() == original.read_bytes()
    secreto = "secreto-compartido-api-mcp-con-mas-de-32-caracteres"
    params = {"cliente_id": "C-1013", "categoria": "soporte_tecnico"}
    token = confirmacion.Confirmaciones(secreto).emitir("crearTicket", params, "A-001", "asesor")
    assert mcp.Confirmaciones(secreto).verificar(token, "crearTicket", params).asesor_id == "A-001"
