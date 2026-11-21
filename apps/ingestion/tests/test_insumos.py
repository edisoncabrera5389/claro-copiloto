"""Corpus real completo en memoria (se omite sin insumos): duplicados, versiones, PII y frescura del v2."""

import re

import pytest

from .conftest import RAW, requiere_insumos

pytestmark = requiere_insumos


@pytest.fixture
def corpus(entorno):
    archivos = sorted((RAW / "01_documentos").rglob("*.*")) + sorted(
        (RAW / "02_transcripciones" / "llamadas").glob("*.txt")
    )
    resultados = {p.name: entorno.pipeline.procesar(p) for p in archivos}
    return entorno, resultados


def test_corpus_completo(corpus):
    e, r = corpus
    estados = [x["resultado"] for x in r.values()]
    assert estados.count("indexado") == 63 and estados.count("formato_alterno") == 6
    alternos = sorted(n for n, x in r.items() if x["resultado"] == "formato_alterno")
    assert alternos == sorted(
        f"{n}.pdf"
        for n in (
            "Contrato_Servicios_Hogar",
            "Contrato_Servicios_Movil_Pospago",
            "Politica_Escalamiento_Atencion",
            "Politica_Facturacion_y_Pagos",
            "Politica_Portabilidad_Numerica",
            "Politica_Retencion_Clientes",
        )
    )


@pytest.mark.parametrize(
    ("archivo", "version"),
    [
        ("Politica_Retencion_Clientes.docx", "3.1"),
        ("Contrato_Servicios_Hogar.docx", "2.0"),
        ("Politica_Facturacion_y_Pagos.docx", "2.2"),
        ("Catalogo_Planes_Claro_2026.pdf", "1.0"),
    ],
)
def test_versiones_leidas_del_documento(corpus, archivo, version):
    assert corpus[1][archivo]["version"] == version


def test_matriz_de_retencion_como_tabla_completa(corpus):
    e, _ = corpus
    hits = e.indice.buscar("RET-A antigüedad más de 24 meses", e.embedder, k=3)
    tabla = next(h for h in hits if h["es_tabla"])
    assert (
        tabla["fuente"] == "Politica_Retencion_Clientes.docx" and tabla["seccion"] == "3. Matriz de ofertas"
    )
    assert all(t in tabla["texto"] for t in ("30 %", "6 meses", "Upgrade", "10 GB"))


def test_ninguna_transcripcion_indexada_conserva_documentos(corpus):
    e, _ = corpus
    puntos, _ = e.indice.cliente.scroll("conocimiento", limit=2000, with_payload=True)
    textos = [p.payload["texto"] for p in puntos if p.payload["tipo"] == "transcripcion"]
    assert len(textos) == 50
    assert not [t for t in textos if re.search(r"(?<!\d)\d{6,10}(?!\d)|3\d{2} \d{3} \d{4}", t)]


def test_frescura_catalogo_v2(corpus):
    e, _ = corpus
    r = e.pipeline.procesar(RAW / "06_actualizaciones" / "Catalogo_Planes_Claro_2026_v2.pdf")
    assert (r["resultado"], r["version"], r["vigente"]) == ("indexado", "2.0", True)
    assert e.indice.contar(doc_id="catalogo_planes_claro_2026", version="1.0", vigente=True) == 0
    hits = e.indice.buscar("precio Hogar Fibra 300", e.embedder, k=5)
    assert hits[0]["fuente"] == "Catalogo_Planes_Claro_2026_v2.pdf" and "$84.900" in hits[0]["texto"]
    assert hits[0]["vigente_desde"] == "2026-12-01"
    assert "Catalogo_Planes_Claro_2026.pdf" not in {h["fuente"] for h in hits}  # el v1 ya no se cita
    assert e.registro.frescura()["cumple"]
