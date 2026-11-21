"""Reglas del pipeline: idempotencia, versiones, formatos alternos, vigencia, PII, linaje y frescura."""

import re
from datetime import UTC, datetime

from qdrant_client import models

from .conftest import crear_docx, crear_eml, crear_md, crear_pdf, crear_transcripcion


def payloads(e, **igual):
    must = [models.FieldCondition(key=k, match=models.MatchValue(value=v)) for k, v in igual.items()]
    puntos, _ = e.indice.cliente.scroll(
        "conocimiento", scroll_filter=models.Filter(must=must), limit=500, with_payload=True
    )
    return [p.payload for p in puntos]


def test_indexa_con_metadatos_completos(entorno, tmp_path):
    r = entorno.pipeline.procesar(crear_docx(tmp_path / "Politica_Prueba.docx"))
    assert (r["resultado"], r["version"], r["vigente"], r["fragmentos"]) == ("indexado", "3.1", True, 4)
    p = payloads(entorno, doc_id="politica_prueba")[0]
    for campo in (
        "doc_id",
        "version",
        "vigente",
        "titulo",
        "seccion",
        "tipo",
        "servicio",
        "fuente",
        "formato",
        "codigo",
        "hash_documento",
        "fecha_indexado",
        "embedding",
        "disperso",
        "texto",
        "orden",
        "es_tabla",
    ):
        assert campo in p
    assert (p["codigo"], p["tipo"], p["fuente"], p["disperso"]) == (
        "POL-PRU-2026",
        "politica",
        "Politica_Prueba.docx",
        "bm25-codigos-v1",
    )
    doc = entorno.registro.documento("politica_prueba")
    assert doc["version_vigente"] == "3.1" and doc["versiones"][0]["fragmentos"] == 4


def test_mismo_archivo_dos_veces_es_idempotente(entorno, tmp_path):
    ruta = crear_md(tmp_path / "FAQ_Prueba.md")
    assert entorno.pipeline.procesar(ruta)["resultado"] == "indexado"
    n = entorno.indice.contar(doc_id="faq_prueba")
    assert entorno.pipeline.procesar(ruta)["resultado"] == "sin_cambios"
    assert entorno.indice.contar(doc_id="faq_prueba") == n


def test_reproceso_forzado_reindexa_la_misma_version(entorno, tmp_path):
    ruta = crear_md(tmp_path / "FAQ_Prueba.md")
    entorno.pipeline.procesar(ruta)
    r = entorno.pipeline.procesar(ruta, forzar=True)
    assert (r["resultado"], r["version"]) == ("indexado", "1.0")
    assert [v["version"] for v in entorno.registro.documento("faq_prueba")["versiones"]] == ["1.0"]


def test_docx_y_pdf_de_la_misma_version_se_indexan_una_vez(entorno, tmp_path):
    crear_docx(tmp_path / "Politica_Dual.docx", version="2.0")
    crear_pdf(tmp_path / "Politica_Dual.pdf", version="2.0")
    assert entorno.pipeline.procesar(tmp_path / "Politica_Dual.docx")["resultado"] == "indexado"
    r = entorno.pipeline.procesar(tmp_path / "Politica_Dual.pdf")
    assert r["resultado"] == "formato_alterno" and r["preferido"] == "Politica_Dual.docx"
    assert {p["formato"] for p in payloads(entorno, doc_id="politica_dual")} == {"docx"}
    assert [a["fuente"] for a in entorno.registro.documento("politica_dual")["alternos"]] == [
        "Politica_Dual.pdf"
    ]


def test_si_llega_primero_el_pdf_el_docx_lo_reemplaza(entorno, tmp_path):
    crear_pdf(tmp_path / "Politica_Dual.pdf", version="2.0")
    crear_docx(tmp_path / "Politica_Dual.docx", version="2.0")
    entorno.pipeline.procesar(tmp_path / "Politica_Dual.pdf")
    r = entorno.pipeline.procesar(tmp_path / "Politica_Dual.docx")
    assert r["resultado"] == "indexado" and r["reemplaza_formato"] == "Politica_Dual.pdf"
    assert {p["formato"] for p in payloads(entorno, doc_id="politica_dual")} == {"docx"}
    doc = entorno.registro.documento("politica_dual")
    assert [v["formato"] for v in doc["versiones"]] == ["docx"] and doc["alternos"][0]["formato"] == "pdf"


def test_sin_version_declarada_otro_formato_es_alterno_y_mismo_formato_es_version_nueva(entorno, tmp_path):
    (tmp_path / "a").mkdir()
    crear_md(tmp_path / "Guia_Prueba.md")
    entorno.pipeline.procesar(tmp_path / "Guia_Prueba.md")
    otro = tmp_path / "a" / "Guia_Prueba.md"
    otro.write_text("# Guía\n\n## Nueva sección\n\nContenido actualizado.\n", encoding="utf-8")
    r = entorno.pipeline.procesar(otro)
    assert (r["resultado"], r["version"]) == ("indexado", "2.0")


def test_nueva_version_deja_la_anterior_no_vigente(entorno, tmp_path):
    (tmp_path / "v2").mkdir()
    v1 = crear_pdf(tmp_path / "Catalogo_Prueba.pdf", version="1.0", precio="$89.900")
    v2 = crear_pdf(tmp_path / "v2" / "Catalogo_Prueba_v2.pdf", version="2.0", precio="$84.900")
    entorno.pipeline.procesar(v1)
    r = entorno.pipeline.procesar(v2, t_detectado=datetime(2026, 11, 21, 12, 0, tzinfo=UTC))
    assert (r["version"], r["vigente"]) == ("2.0", True) and r["frescura_s"] > 0
    assert entorno.indice.contar(doc_id="catalogo_prueba", version="1.0", vigente=True) == 0
    assert entorno.indice.contar(doc_id="catalogo_prueba", version="1.0") > 0  # se conserva para auditoría
    resultados = entorno.indice.buscar("precio Hogar Fibra 300", entorno.embedder, k=3)
    assert {h["version"] for h in resultados} == {"2.0"} and any("$84.900" in h["texto"] for h in resultados)
    historico = entorno.indice.buscar("precio Hogar Fibra 300", entorno.embedder, k=10, solo_vigentes=False)
    assert {h["version"] for h in historico} == {"1.0", "2.0"}
    assert entorno.registro.documento("catalogo_prueba")["version_vigente"] == "2.0"


def test_revertir_version_devuelve_la_vigencia_a_la_anterior(entorno, tmp_path):
    (tmp_path / "v2").mkdir()
    entorno.pipeline.procesar(crear_pdf(tmp_path / "Catalogo_Prueba.pdf", version="1.0"))
    entorno.pipeline.procesar(
        crear_pdf(tmp_path / "v2" / "Catalogo_Prueba_v2.pdf", version="2.0", precio="$84.900")
    )
    r = entorno.pipeline.revertir("catalogo_prueba", "2.0")
    assert r == {
        "doc_id": "catalogo_prueba",
        "retirada": "2.0",
        "vigente": "1.0",
        "fuentes": ["Catalogo_Prueba_v2.pdf"],
    }
    assert entorno.indice.contar(doc_id="catalogo_prueba", version="2.0") == 0
    assert entorno.indice.contar(doc_id="catalogo_prueba", version="1.0", vigente=True) > 0
    assert entorno.registro.documento("catalogo_prueba")["version_vigente"] == "1.0"
    # El v2 puede volver a llegar (ensayo de la demo de frescura)
    r = entorno.pipeline.procesar(tmp_path / "v2" / "Catalogo_Prueba_v2.pdf")
    assert (r["resultado"], r["version"], r["vigente"]) == ("indexado", "2.0", True)
    assert entorno.pipeline.revertir("no_existe", "1.0")["vigente"] is None


def test_version_vieja_que_llega_tarde_no_queda_vigente(entorno, tmp_path):
    (tmp_path / "v1").mkdir()
    entorno.pipeline.procesar(crear_pdf(tmp_path / "Catalogo_Prueba_v2.pdf", version="2.0"))
    r = entorno.pipeline.procesar(
        crear_pdf(tmp_path / "v1" / "Catalogo_Prueba.pdf", version="1.0", precio="$1")
    )
    assert (r["version"], r["vigente"]) == ("1.0", False)
    assert entorno.registro.documento("catalogo_prueba")["version_vigente"] == "2.0"
    assert entorno.indice.contar(doc_id="catalogo_prueba", version="2.0", vigente=True) > 0


def test_transcripcion_anonimizada_en_indice_y_registro(entorno, tmp_path):
    r = entorno.pipeline.procesar(crear_transcripcion(tmp_path / "TRX-9001.txt"))
    assert r["pii"] == {"PERSON": 2, "CO_DOCUMENTO": 1, "CO_CELULAR": 1}
    textos = " ".join(p["texto"] for p in payloads(entorno, doc_id="trx_9001"))
    guardada = entorno.registro.transcripciones.find_one({"_id": "trx_9001"})
    for fuga in ("Juliana", "Marcela", "359268319", "312 527 3199"):
        assert fuga not in textos and fuga not in guardada["texto"]
    assert guardada["metadatos"]["ciudad"] == "Villavicencio"
    # No aparece en la búsqueda de conocimiento salvo que se pida
    assert not entorno.indice.buscar("cliente documento", entorno.embedder, k=5)
    assert entorno.indice.buscar("cliente documento", entorno.embedder, k=5, incluir_transcripciones=True)


def test_correo_usa_modo_completo_y_documentos_solo_reglas(entorno, tmp_path):
    r = entorno.pipeline.procesar(crear_eml(tmp_path / "01_aviso.eml"))
    assert r["pii"] == {"PERSON": 1, "EMAIL_ADDRESS": 1, "CO_CELULAR": 1}
    r = entorno.pipeline.procesar(crear_docx(tmp_path / "Politica_Prueba.docx"))
    assert r["pii"] == {}


def test_omitidos(entorno, tmp_path):
    (tmp_path / "foto.png").write_bytes(b"x")
    assert entorno.pipeline.procesar(tmp_path / "foto.png")["motivo"].startswith("formato no soportado")
    assert entorno.pipeline.procesar(tmp_path / "No_Existe.pdf")["motivo"] == "el archivo ya no existe"
    assert entorno.registro.ingestas.count_documents({"resultado": "omitido"}) == 2


def test_linaje_y_frescura_quedan_registrados(entorno, tmp_path):
    entorno.pipeline.procesar(crear_md(tmp_path / "FAQ_Prueba.md"), evento_id="1-0")
    ing = entorno.registro.ingestas.find_one({"evento_id": "1-0"})
    assert ing["resultado"] == "indexado" and re.fullmatch(r"[0-9a-f]{64}", ing["hash"])
    assert ing["frescura_s"] >= ing["duracion_s"] > 0
    f = entorno.registro.frescura()
    assert f["n"] == 1 and f["cumple"] and f["meta_s"] == 900
    assert entorno.registro.resumen()[0]["fuente_vigente"] == "FAQ_Prueba.md"


def test_frescura_sin_datos(entorno):
    assert entorno.registro.frescura() == {"n": 0}
