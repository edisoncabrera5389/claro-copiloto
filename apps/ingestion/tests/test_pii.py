import re

import pytest

from ingesta.pii import redactar_reglas

from .conftest import RAW, requiere_insumos

DIALOGO = (
    "ASESOR: Bienvenido a Claro, habla con Marcela. ¿Con quién tengo el gusto?\n"
    "CLIENTE: Hola, con Juliana Mejía Martínez. Vivo en Villavicencio.\n"
    "CLIENTE: Sí, es 359268319. Mi celular es 312 527 3199 y mi correo juli@correo-ficticio.co\n"
    "ASESOR: Le ofrezco Claro Video y el plan Hogar Fibra 500 por $109.900."
)


def test_modo_completo_anonimiza_personas_documento_celular_y_correo(anonimizador):
    texto, conteo = anonimizador.anonimizar(DIALOGO)
    for dato in ("Marcela", "Juliana", "Mejía", "359268319", "312 527 3199", "juli@"):
        assert dato not in texto
    assert (
        texto.count("<PERSONA>") == 2
        and "<DOCUMENTO>" in texto
        and "<CELULAR>" in texto
        and "<CORREO>" in texto
    )
    assert conteo == {"PERSON": 2, "CO_DOCUMENTO": 1, "CO_CELULAR": 1, "EMAIL_ADDRESS": 1}


def test_no_borra_marca_ciudad_etiquetas_ni_montos(anonimizador):
    texto, _ = anonimizador.anonimizar(DIALOGO)
    for conservado in (
        "Claro",
        "Villavicencio",
        "ASESOR:",
        "CLIENTE:",
        "Claro Video",
        "Hogar Fibra 500",
        "$109.900",
    ):
        assert conservado in texto


def test_modo_reglas_no_usa_ner(anonimizador):
    texto, conteo = anonimizador.anonimizar("Juliana pagó con CC 1.023.456.789 y $150.000", modo="reglas")
    assert texto == "Juliana pagó con CC <DOCUMENTO> y $150.000"
    assert conteo == {"CO_DOCUMENTO": 1}


@pytest.mark.parametrize(
    "texto",
    [
        "Ajuste de $150.000",
        "Ticket TK-990001 del cliente C-1004",
        "Fecha 2026-11-12",
        "Plan de 500 Mbps",
        "E-202",
    ],
)
def test_reglas_no_tocan_montos_ids_ni_codigos(texto):
    assert redactar_reglas(texto) == (texto, {})


@pytest.mark.parametrize(
    "texto",
    [
        "Buenas tardes, habla con Luisa de Claro. Cliente, hola.",  # así transcribe Whisper los audios
        "Buenos días, habla con Jorge de Claro. Cliente, buenos días.",
    ],
)
def test_nombre_seguido_de_la_marca_se_anonimiza_sin_borrar_la_marca(anonimizador, texto):
    salida, conteo = anonimizador.anonimizar(texto)
    assert "Luisa" not in salida and "Jorge" not in salida
    assert "<PERSONA> de Claro" in salida and conteo["PERSON"] == 1


def test_texto_vacio_y_solapes(anonimizador):
    assert anonimizador.anonimizar("")[0] == ""
    texto, _ = anonimizador.anonimizar("Le habla Pedro Pérez, documento 1023456789.")
    assert "Pedro" not in texto and "1023456789" not in texto


@requiere_insumos
def test_cero_fugas_en_las_50_transcripciones_reales(anonimizador):
    fugas = []
    for p in sorted((RAW / "02_transcripciones" / "llamadas").glob("TRX-*.txt")):
        orig = p.read_text(encoding="utf-8")
        texto, _ = anonimizador.anonimizar(orig)
        sensibles = (
            re.findall(r"CLIENTE: [^\n]*?con ([A-ZÁÉÍÓÚÑ]\w+(?: [A-ZÁÉÍÓÚÑ]\w+)+)", orig)
            + re.findall(r"habla con (\w+)", orig)
            + re.findall(r"(?<!\d)\d{6,10}(?!\d)", orig)
            + re.findall(r"3\d{2} \d{3} \d{4}", orig)
        )
        fugas += [(p.name, s) for s in sensibles if s in texto]
        assert "Claro" in texto
    assert fugas == []
