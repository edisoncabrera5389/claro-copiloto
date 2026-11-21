from ingesta import extractores
from ingesta.extractores import extraer, extraer_pdf, extraer_wav, tabla_markdown
from ingesta.identificacion import identificar

from .conftest import crear_docx, crear_eml, crear_md, crear_pdf, crear_pdf_imagen, crear_transcripcion


def test_tabla_markdown_une_encabezado_partido_y_compacta_celdas():
    filas = [
        ["Plan", "Velocidad", "", "Precio", "", "Incluye"],
        [None, None, None, "mensual", None, None],
        ["Hogar Fibra 300", "300 Mbps", "$89.900", None, None, "Módem\nWiFi 6"],
    ]
    assert tabla_markdown(filas) == (
        "| Plan | Velocidad | Precio mensual | Incluye |\n|---|---|---|---|\n"
        "| Hogar Fibra 300 | 300 Mbps | $89.900 | Módem WiFi 6 |"
    )


def test_tabla_markdown_quita_repeticiones_de_celdas_combinadas_y_vacias():
    assert tabla_markdown([["A", "B"], ["x", "x"], [None, None]]) == "| A | B |\n|---|---|\n| x |"
    assert tabla_markdown([[None, ""]]) == ""


def test_docx_lee_encabezado_de_pagina_secciones_listas_y_tablas(tmp_path, settings):
    ruta = crear_docx(tmp_path / "Politica_Prueba.docx")
    d = extraer(ruta, identificar(ruta), settings)
    assert d.titulo == "Política de Prueba"
    assert "Versión 3.1" in d.texto_cabecera  # vive en el header, no en el cuerpo
    assert [b.seccion for b in d.bloques] == ["1. Objetivo", "2. Criterios", "2. Criterios", "2. Criterios"]
    tabla = next(b for b in d.bloques if b.es_tabla)
    assert "| Menos de 12 meses | Repetidor |" in tabla.texto  # celdas repetidas compactadas
    assert d.bloques[1].texto == "- Sin mora mayor a 30 días."


def test_pdf_tablas_en_su_seccion_sin_pies_ni_pasos_como_titulos(tmp_path, settings):
    ruta = crear_pdf(tmp_path / "Catalogo_Prueba.pdf")
    d = extraer(ruta, identificar(ruta), settings)
    assert d.titulo == "Catalogo de Prueba"
    assert "Version 1.0" in d.texto_cabecera
    secciones = {b.seccion for b in d.bloques}
    assert secciones == {"1. Alcance", "2. Internet Hogar", "3. Movil", "4. Promociones"}
    tabla = next(b for b in d.bloques if b.es_tabla)
    assert tabla.seccion == "2. Internet Hogar" and "| Hogar Fibra 300 | $89.900 |" in tabla.texto
    assert "Hogar Fibra 300" not in "".join(b.texto for b in d.bloques if not b.es_tabla)  # no se duplica
    assert "DOCUMENTO FICTICIO" not in d.texto and "Vigente desde" not in d.texto  # encabezado/pie repetidos
    assert next(b for b in d.bloques if b.seccion == "4. Promociones").pagina == 2
    assert d.metadatos == {"paginas": 2, "ocr_paginas": []}


def test_pdf_sin_capa_de_texto_usa_ocr(tmp_path, settings):
    ruta = crear_pdf_imagen(tmp_path / "Escaneado.pdf")
    llamadas = []

    def ocr_falso(pagina, lang):
        llamadas.append(lang)
        return "1. Objeto\nTexto reconocido por OCR desde la imagen."

    d = extraer_pdf(ruta, settings, ocr=ocr_falso)
    assert llamadas == ["spa"] and d.metadatos["ocr_paginas"] == [1]
    assert d.bloques[0].seccion == "1. Objeto" and "reconocido por OCR" in d.bloques[0].texto


def test_markdown_por_secciones(tmp_path, settings):
    ruta = crear_md(tmp_path / "FAQ_Prueba.md")
    d = extraer(ruta, identificar(ruta), settings)
    assert d.titulo == "Preguntas frecuentes"
    assert [b.seccion for b in d.bloques] == [None, "¿Cómo pago?", "Error E-202"]


def test_correo(tmp_path, settings):
    ruta = crear_eml(tmp_path / "01_recordatorio.eml")
    d = extraer(ruta, identificar(ruta), settings)
    assert d.titulo == "Recordatorio de prueba" and d.metadatos["fecha"].startswith("2026-11-09T08:15")
    assert "Asunto: Recordatorio de prueba" in d.texto and "Laura Gómez" in d.texto


def test_correo_html(tmp_path, settings):
    ruta = tmp_path / "html.eml"
    ruta.write_text(
        "Subject: X\nContent-Type: text/html; charset=utf-8\n\n<p>Hola &amp; adi&oacute;s</p>\n",
        encoding="utf-8",
    )
    assert "Hola & adiós" in extraer(ruta, identificar(ruta), settings).texto


def test_transcripcion_con_metadatos(tmp_path, settings):
    ruta = crear_transcripcion(tmp_path / "TRX-9001.txt")
    d = extraer(ruta, identificar(ruta), settings)
    assert d.titulo == "Transcripción TRX-9001"
    assert d.metadatos["ciudad"] == "Villavicencio" and d.metadatos["canal"] == "chat"
    assert (
        d.bloques[0].texto.startswith("ASESOR:")
        and d.bloques[0].seccion == "chat · 2026-10-01T11:12 · Villavicencio"
    )


def test_audio_con_asr_inyectado(tmp_path, settings):
    ruta = tmp_path / "AUD-0001.wav"
    ruta.write_bytes(b"RIFF")
    d = extraer_wav(ruta, settings, transcribir=lambda r, s: ("Hola, quiero cancelar.", {"duracion_s": 3.0}))
    assert (
        d.titulo == "Audio AUD-0001"
        and d.texto == "Hola, quiero cancelar."
        and d.metadatos["duracion_s"] == 3.0
    )


def test_despacho_por_formato():
    assert set(extractores.EXTRACTORES) == {"pdf", "docx", "md", "eml", "txt", "wav"}


def test_txt_sin_cabecera(tmp_path, settings):
    ruta = tmp_path / "TRX-9002.txt"
    ruta.write_text("solo texto", encoding="utf-8")
    d = extraer(ruta, identificar(ruta), settings)
    assert d.metadatos == {} and d.bloques[0].seccion is None


def test_whisper_se_carga_una_vez(monkeypatch, tmp_path, settings):
    import sys
    import types

    cargas = []

    class Seg:
        text = " Hola "

    class Info:
        duration, language, language_probability = 2.04, "es", 0.987

    class ModeloFalso:
        def __init__(self, *a, **k):
            cargas.append(k)

        def transcribe(self, audio, language, vad_filter):
            assert audio.dtype.name == "float32" and len(audio) == 16_000  # ya decodificado y remuestreado
            return [Seg(), Seg()], Info()

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=ModeloFalso))
    monkeypatch.setattr(extractores, "_whisper", {})
    ruta = crear_wav(tmp_path / "a.wav", frecuencia=22_050, segundos=1.0)
    for _ in range(2):
        texto, meta = extractores._transcribir(ruta, settings)
    assert len(cargas) == 1 and cargas[0]["compute_type"] == "int8"
    assert texto == "Hola\nHola" and meta == {
        "asr_modelo": "faster-whisper-small",
        "duracion_s": 2.0,
        "idioma": "es",
        "prob_idioma": 0.987,
    }


def crear_wav(ruta, frecuencia=22_050, segundos=0.5, canales=1, ancho=2):
    import math
    import struct
    import wave

    n = int(frecuencia * segundos)
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(canales)
        w.setsampwidth(ancho)
        w.setframerate(frecuencia)
        muestras = [int(12000 * math.sin(2 * math.pi * 440 * i / frecuencia)) for i in range(n)]
        if ancho == 1:
            w.writeframes(bytes((m // 256 + 128) for m in muestras for _ in range(canales)))
        else:
            w.writeframes(b"".join(struct.pack("<h", m) * canales for m in muestras))
    return ruta


def test_leer_wav_remuestrea_a_16khz_y_mezcla_canales(tmp_path):
    from ingesta.extractores import leer_wav

    audio = leer_wav(crear_wav(tmp_path / "a.wav", frecuencia=22_050, segundos=0.5, canales=2))
    assert audio.dtype.name == "float32" and len(audio) == 8_000 and 0.3 < float(abs(audio).max()) < 0.4
    mono8 = leer_wav(crear_wav(tmp_path / "b.wav", frecuencia=16_000, segundos=0.25, ancho=1))
    assert len(mono8) == 4_000 and float(abs(mono8).max()) <= 1.0


def test_leer_wav_rechaza_formato_no_soportado(tmp_path):
    import wave

    import pytest

    from ingesta.extractores import leer_wav

    ruta = tmp_path / "c.wav"
    with wave.open(str(ruta), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(3)
        w.setframerate(16_000)
        w.writeframes(b"\x00\x00\x00" * 10)
    with pytest.raises(ValueError, match="24 bits"):
        leer_wav(ruta)


def test_ocr_real_si_tesseract_disponible(tmp_path, settings):
    import shutil

    import pytest

    if not shutil.which("tesseract"):
        pytest.skip("Tesseract no instalado en esta máquina (se verifica en el contenedor)")
    ruta = crear_pdf_imagen(tmp_path / "Escaneado.pdf")
    assert extraer_pdf(ruta, settings).metadatos["ocr_paginas"] == [1]
