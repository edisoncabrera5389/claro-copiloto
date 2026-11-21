from pathlib import Path

import pytest

from ingesta.identificacion import (
    detectar_codigo,
    detectar_version,
    detectar_vigente_desde,
    identificar,
    siguiente_version,
    version_tupla,
)


@pytest.mark.parametrize(
    ("nombre", "doc_id", "tipo", "servicio", "formato"),
    [
        ("Catalogo_Planes_Claro_2026.pdf", "catalogo_planes_claro_2026", "catalogo", "general", "pdf"),
        ("Catalogo_Planes_Claro_2026_v2.pdf", "catalogo_planes_claro_2026", "catalogo", "general", "pdf"),
        ("Contrato_Servicios_Hogar.docx", "contrato_servicios_hogar", "contrato", "hogar", "docx"),
        (
            "Contrato_Servicios_Movil_Pospago.pdf",
            "contrato_servicios_movil_pospago",
            "contrato",
            "movil",
            "pdf",
        ),
        ("Politica_Retencion_Clientes.docx", "politica_retencion_clientes", "politica", "general", "docx"),
        ("Manual_Modem_ZTX-F680.pdf", "manual_modem_ztx_f680", "manual", "hogar", "pdf"),
        ("FAQ_Atencion_Clientes.md", "faq_atencion_clientes", "faq", "general", "md"),
        ("02_incidente_masivo_chapinero.eml", "02_incidente_masivo_chapinero", "correo", "general", "eml"),
        ("TRX-0001.txt", "trx_0001", "transcripcion", "general", "txt"),
        ("AUD-0001.wav", "aud_0001", "transcripcion", "general", "wav"),
        ("Otro Documento Ñandú.docx", "otro_documento_nandu", "documento", "general", "docx"),
    ],
)
def test_identidad_por_nombre(nombre, doc_id, tipo, servicio, formato):
    i = identificar(Path(nombre))
    assert (i.doc_id, i.tipo, i.servicio, i.formato, i.fuente) == (doc_id, tipo, servicio, formato, nombre)


@pytest.mark.parametrize(
    "nombre",
    [
        "~$Politica.docx",
        ".oculto.pdf",
        "copia.pdf.part",
        "imagen.png",
        "indice_transcripciones.csv",
        "LEEME.md",
    ],
)
def test_archivos_ignorados(nombre):
    assert identificar(Path(nombre)) is None


def test_version_del_contenido_manda_sobre_el_nombre():
    assert detectar_version("CAT-2026 · Versión 2.0 · Vigente", "Catalogo_v3.pdf") == "2.0"
    assert detectar_version("sin versión aquí", "Catalogo_Planes_v2.pdf") == "2.0"
    assert detectar_version("Version 3", "x.pdf") == "3.0"
    assert detectar_version("nada", "x.pdf") is None


def test_codigo_y_vigencia():
    cab = "POL-RET-2026 · Versión 3.1 · Vigente desde 01/12/2026"
    assert detectar_codigo(cab) == "POL-RET-2026"
    assert detectar_codigo("CAT-2026 · Versión 1.0") == "CAT-2026"
    assert detectar_vigente_desde(cab) == "2026-12-01"
    assert detectar_vigente_desde("Vigente desde 31/02/2026") is None
    assert detectar_codigo("sin código") is None and detectar_vigente_desde("x") is None


def test_comparacion_de_versiones():
    assert version_tupla("10.1") > version_tupla("9.9") > version_tupla("2")
    assert version_tupla("sin") == (0,)
    assert siguiente_version("2.2") == "3.0"
