"""Extracción por formato → bloques estructurados (secciones y tablas).

PDF (pdfplumber, OCR con Tesseract si la página no tiene capa de texto) · DOCX · Markdown · EML ·
transcripción TXT · audio WAV (faster-whisper). Las tablas se conservan completas como Markdown.
"""

import email
import email.policy
import html
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ingesta.config import Settings
from ingesta.modelos import Bloque, DocumentoExtraido, Identidad

_TITULO_NUMERADO = re.compile(r"^(\d{1,2})\.\s+([A-ZÁÉÍÓÚÑ¿].{2,78})$")
_PIE_PAGINA = re.compile(r"DOCUMENTO FICTICIO|P[áa]g\.\s*\d+", re.IGNORECASE)


# ----------------------------------------------------------------------------------- tablas ----


def _celda(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v)).strip() if v is not None else ""


def tabla_markdown(filas: list[list[Any]]) -> str:
    """Normaliza una tabla (de pdfplumber o DOCX) a Markdown.

    pdfplumber rellena con None las celdas combinadas y parte encabezados en dos filas ("Precio" /
    "mensual"): se compactan las celdas y las filas de continuación se unen a la columna de arriba.
    """
    filas = [list(f) for f in filas if any(_celda(c) for c in f)]
    if not filas:
        return ""
    cab_pos = [(i, _celda(c)) for i, c in enumerate(filas[0]) if _celda(c)]
    cuerpo = filas[1:]
    while cuerpo and not _celda(cuerpo[0][0]) and len([c for c in cuerpo[0] if _celda(c)]) < len(cab_pos):
        for j, c in enumerate(cuerpo.pop(0)):  # continuación del encabezado
            if _celda(c):
                k = max((n for n, (i, _) in enumerate(cab_pos) if i <= j), default=0)
                cab_pos[k] = (cab_pos[k][0], f"{cab_pos[k][1]} {_celda(c)}")
    cabecera = [t for _, t in cab_pos]
    lineas = ["| " + " | ".join(cabecera) + " |", "|" + "---|" * len(cabecera)]
    for f in cuerpo:
        celdas: list[str] = []
        for c in map(_celda, f):
            if c and (not celdas or celdas[-1] != c):  # DOCX repite el texto de celdas combinadas
                celdas.append(c)
        lineas.append("| " + " | ".join(celdas) + " |")
    return "\n".join(lineas)


# ------------------------------------------------------------------------------------- PDF -----


def _ocr_pagina(pagina: Any, lang: str) -> str:
    import pytesseract

    imagen = pagina.to_image(resolution=300).original
    return pytesseract.image_to_string(imagen, lang=lang)


def _lineas_repetidas(paginas: list[list[str]]) -> set[str]:
    """Encabezados y pies: líneas que se repiten en 2+ páginas (ignorando números)."""
    if len(paginas) < 2:
        return set()
    conteo: Counter[str] = Counter()
    for lns in paginas:
        for norm in {re.sub(r"\d+", "#", ln) for ln in lns}:
            conteo[norm] += 1
    return {n for n, c in conteo.items() if c >= 2}


def extraer_pdf(ruta: Path, s: Settings, ocr: Callable[[Any, str], str] = _ocr_pagina) -> DocumentoExtraido:
    import pdfplumber

    # Por página: elementos ("linea" | "tabla", texto) en orden vertical, para que cada tabla quede
    # en la sección donde realmente está y no al final de la página.
    paginas: list[list[tuple[str, str]]] = []
    ocr_paginas: list[int] = []
    with pdfplumber.open(ruta) as pdf:
        for n, pag in enumerate(pdf.pages, start=1):
            tablas = pag.find_tables()
            cajas = [t.bbox for t in tablas]

            def fuera_de_tablas(obj: dict, cajas: list = cajas) -> bool:
                cx = (obj.get("x0", 0) + obj.get("x1", 0)) / 2
                cy = (obj.get("top", 0) + obj.get("bottom", 0)) / 2
                return not any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in cajas)

            base = pag.filter(fuera_de_tablas) if cajas else pag
            items = [
                (ln["top"], "linea", ln["text"].strip())
                for ln in base.extract_text_lines()
                if ln["text"].strip()
            ]
            items += [(t.bbox[1], "tabla", md) for t in tablas if (md := tabla_markdown(t.extract()))]
            if sum(len(t) for _, k, t in items if k == "linea") < s.ocr_min_chars and not tablas:
                lineas_ocr = [ln.strip() for ln in ocr(pag, s.tesseract_lang).splitlines() if ln.strip()]
                items = [(float(i), "linea", ln) for i, ln in enumerate(lineas_ocr)]
                ocr_paginas.append(n)
            paginas.append([(k, t) for _, k, t in sorted(items, key=lambda x: x[0])])

    lineas_pag = [[t for k, t in p if k == "linea"] for p in paginas]
    cabecera = "\n".join(lineas_pag[0][:3]) if lineas_pag else ""
    primera_linea = lineas_pag[0][0] if lineas_pag and lineas_pag[0] else ""
    repetidas = _lineas_repetidas(lineas_pag)
    titulo: str | None = None
    bloques: list[Bloque] = []
    seccion, pagina_seccion, buffer, ultimo_num = None, 1, [], 0

    def cerrar() -> None:
        if buffer:
            bloques.append(Bloque("\n".join(buffer), seccion, pagina_seccion))
            buffer.clear()

    for n, elementos in enumerate(paginas, start=1):
        for clase, ln in elementos:
            if clase == "tabla":
                cerrar()
                bloques.append(Bloque(ln, seccion, n, es_tabla=True))
                continue
            if re.sub(r"\d+", "#", ln) in repetidas or _PIE_PAGINA.search(ln):
                continue
            m = _TITULO_NUMERADO.match(ln)
            # Título de sección solo si sigue la numeración (1, 2, 3…): los pasos "1. Conéctese…" no cortan.
            if m and int(m.group(1)) == ultimo_num + 1 and not ln.endswith("."):
                cerrar()
                seccion, pagina_seccion, ultimo_num = ln, n, int(m.group(1))
            elif n == 1 and titulo is None and seccion is None and len(ln) < 90 and ln != primera_linea:
                titulo = ln  # primera línea "de verdad" antes de la sección 1 (la 1.ª suele ser el código)
            else:
                if not buffer:
                    pagina_seccion = n
                buffer.append(ln)
    cerrar()
    return DocumentoExtraido(bloques, titulo, {"paginas": len(paginas), "ocr_paginas": ocr_paginas}, cabecera)


# ------------------------------------------------------------------------------------ DOCX -----


def extraer_docx(ruta: Path, s: Settings) -> DocumentoExtraido:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    documento = docx.Document(str(ruta))
    titulo: str | None = None
    bloques: list[Bloque] = []
    seccion: str | None = None
    buffer: list[str] = []
    # El código y la versión ("CON-HOG-2026 · Versión 2.0") viven en el encabezado de página, que no
    # forma parte del cuerpo: sin esto, DOCX y PDF del mismo documento parecían versiones distintas.
    cabecera: list[str] = [
        p.text.strip() for sec in documento.sections for p in sec.header.paragraphs if p.text.strip()
    ]

    def cerrar() -> None:
        if buffer:
            bloques.append(Bloque("\n".join(buffer), seccion))
            buffer.clear()

    for hijo in documento.element.body.iterchildren():
        if hijo.tag.endswith("}tbl"):
            cerrar()
            tabla = Table(hijo, documento)
            if md := tabla_markdown([[c.text for c in fila.cells] for fila in tabla.rows]):
                bloques.append(Bloque(md, seccion, es_tabla=True))
            continue
        if not hijo.tag.endswith("}p"):
            continue
        p = Paragraph(hijo, documento)
        texto = p.text.strip()
        if not texto:
            continue
        if len(cabecera) < 8:
            cabecera.append(texto)
        estilo = (p.style.name if p.style is not None else "").lower()
        if estilo in ("title", "título") and titulo is None:
            titulo = texto
        elif estilo.startswith(("heading", "título", "encabezado")):
            cerrar()
            seccion = texto
        else:
            buffer.append(f"- {texto}" if "list" in estilo else texto)
    cerrar()
    return DocumentoExtraido(bloques, titulo, {}, "\n".join(cabecera))


# ------------------------------------------------------------------------------- Markdown ------


def extraer_md(ruta: Path, s: Settings) -> DocumentoExtraido:
    titulo, seccion, buffer, bloques = None, None, [], []
    texto = ruta.read_text(encoding="utf-8-sig")
    for ln in texto.splitlines():
        if ln.startswith("# ") and titulo is None:
            titulo = ln[2:].strip()
        elif re.match(r"^#{2,3}\s", ln):
            if buffer and "".join(buffer).strip():
                bloques.append(Bloque("\n".join(buffer).strip(), seccion))
            seccion, buffer = ln.lstrip("#").strip(), []
        else:
            buffer.append(ln)
    if buffer and "".join(buffer).strip():
        bloques.append(Bloque("\n".join(buffer).strip(), seccion))
    return DocumentoExtraido(bloques, titulo, {}, texto[:600])


# ------------------------------------------------------------------------------------ EML ------


def extraer_eml(ruta: Path, s: Settings) -> DocumentoExtraido:
    msg = email.message_from_bytes(ruta.read_bytes(), policy=email.policy.default)
    cuerpo_part = msg.get_body(preferencelist=("plain", "html"))
    cuerpo = cuerpo_part.get_content() if cuerpo_part else ""
    if cuerpo_part is not None and cuerpo_part.get_content_type() == "text/html":
        cuerpo = html.unescape(re.sub(r"<[^>]+>", " ", cuerpo))
    asunto = str(msg.get("subject", "")).strip()
    fecha = msg.get("date")
    meta = {
        "asunto": asunto,
        "de": str(msg.get("from", "")),
        "fecha": fecha.datetime.isoformat() if fecha and fecha.datetime else None,
    }
    texto = f"Asunto: {asunto}\nFecha: {msg.get('date', '')}\n\n{cuerpo.strip()}"
    return DocumentoExtraido([Bloque(texto, asunto)], asunto or None, meta, texto[:600])


# --------------------------------------------------------------------------- transcripción -----


def extraer_txt(ruta: Path, s: Settings) -> DocumentoExtraido:
    texto = ruta.read_text(encoding="utf-8-sig")
    meta: dict[str, Any] = {}
    cuerpo = texto
    if "\n---" in texto:
        cab, cuerpo = texto.split("\n---", 1)
        for ln in cab.splitlines():
            if ":" in ln:
                k, v = ln.split(":", 1)
                meta[k.strip().lower()] = v.strip()
    titulo = f"Transcripción {meta.get('id', ruta.stem)}"
    seccion = " · ".join(str(meta[k]) for k in ("canal", "fecha", "ciudad") if k in meta) or None
    return DocumentoExtraido([Bloque(cuerpo.strip(), seccion)], titulo, meta, texto[:400])


_whisper: dict[str, Any] = {}


MUESTREO_WHISPER = 16_000


def leer_wav(ruta: Path) -> Any:
    """WAV → float32 mono a 16 kHz, solo con la librería estándar y numpy.

    faster-whisper 1.2.1 decodifica con PyAV pasando `metadata_errors`, parámetro que PyAV 19 eliminó
    (TypeError en los 3 audios). Decodificar aquí evita depender de esa combinación de versiones.
    """
    import wave

    import numpy as np

    with wave.open(str(ruta), "rb") as w:
        canales, ancho, frecuencia = w.getnchannels(), w.getsampwidth(), w.getframerate()
        crudo = w.readframes(w.getnframes())
    tipos = {1: (np.uint8, 128.0, 128.0), 2: (np.int16, 0.0, 32768.0), 4: (np.int32, 0.0, 2147483648.0)}
    if ancho not in tipos:
        raise ValueError(f"WAV de {ancho * 8} bits no soportado")
    dtype, centro, escala = tipos[ancho]
    audio = (np.frombuffer(crudo, dtype=dtype).astype(np.float32) - centro) / escala
    if canales > 1:
        audio = audio.reshape(-1, canales).mean(axis=1)
    if frecuencia != MUESTREO_WHISPER:  # remuestreo lineal: suficiente para voz
        n = round(len(audio) * MUESTREO_WHISPER / frecuencia)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
    return audio


def _transcribir(ruta: Path, s: Settings) -> tuple[str, dict[str, Any]]:
    from faster_whisper import WhisperModel

    if s.whisper_modelo not in _whisper:  # se carga una vez por proceso (~500 MB el modelo small)
        _whisper[s.whisper_modelo] = WhisperModel(
            s.whisper_modelo, device="cpu", compute_type="int8", download_root=str(s.whisper_dir)
        )
    segmentos, info = _whisper[s.whisper_modelo].transcribe(leer_wav(ruta), language="es", vad_filter=True)
    texto = "\n".join(seg.text.strip() for seg in segmentos if seg.text.strip())
    return texto, {
        "asr_modelo": f"faster-whisper-{s.whisper_modelo}",
        "duracion_s": round(info.duration, 1),
        "idioma": info.language,
        "prob_idioma": round(info.language_probability, 3),
    }


def extraer_wav(
    ruta: Path, s: Settings, transcribir: Callable[[Path, Settings], tuple[str, dict]] = _transcribir
) -> DocumentoExtraido:
    texto, meta = transcribir(ruta, s)
    return DocumentoExtraido([Bloque(texto, "Audio transcrito")], f"Audio {ruta.stem}", meta, texto[:400])


EXTRACTORES: dict[str, Callable[[Path, Settings], DocumentoExtraido]] = {
    "pdf": extraer_pdf,
    "docx": extraer_docx,
    "md": extraer_md,
    "eml": extraer_eml,
    "txt": extraer_txt,
    "wav": extraer_wav,
}


def extraer(ruta: Path, ident: Identidad, s: Settings) -> DocumentoExtraido:
    return EXTRACTORES[ident.formato](ruta, s)
