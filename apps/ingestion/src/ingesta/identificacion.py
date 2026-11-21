"""Identidad lógica de un archivo y detección de versión, código y vigencia."""

import re
import unicodedata
from datetime import date
from pathlib import Path

from ingesta.modelos import Identidad

EXTENSIONES = {".pdf": "pdf", ".docx": "docx", ".md": "md", ".eml": "eml", ".txt": "txt", ".wav": "wav"}
# Con la misma versión, el formato más fiel gana (el golden cita los DOCX de políticas y contratos).
PRIORIDAD_FORMATO = {"docx": 3, "md": 3, "eml": 3, "txt": 3, "wav": 2, "pdf": 1}
# Archivos que no son conocimiento: se ignoran.
IGNORAR = re.compile(r"^(~\$|\.)|\.(tmp|part|crdownload)$|^indice_|^leeme", re.IGNORECASE)

_VERSION_TEXTO = re.compile(r"Versi[oó]n\s+(\d+(?:\.\d+)?)", re.IGNORECASE)
_VERSION_NOMBRE = re.compile(r"[_\-\s]v(\d+(?:\.\d+)?)$", re.IGNORECASE)
_CODIGO = re.compile(r"\b([A-Z]{2,5}(?:-[A-Z]{2,5})?-20\d{2})\b")
_VIGENTE_DESDE = re.compile(r"[Vv]igente desde\s+(?:el\s+)?(\d{1,2})/(\d{1,2})/(\d{4})")


def _slug(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", sin_tildes.lower()).strip("_")


def identificar(ruta: Path) -> Identidad | None:
    formato = EXTENSIONES.get(ruta.suffix.lower())
    if formato is None or IGNORAR.search(ruta.name):
        return None
    base = _VERSION_NOMBRE.sub("", ruta.stem)
    nombre = base.lower()

    if formato == "eml":
        tipo, servicio = "correo", "general"
    elif formato == "wav" or re.match(r"^trx-\d+", nombre):
        tipo, servicio = "transcripcion", "general"
    elif nombre.startswith("catalogo"):
        tipo, servicio = "catalogo", "general"
    elif nombre.startswith("politica"):
        tipo, servicio = "politica", "general"
    elif nombre.startswith("contrato"):
        tipo = "contrato"
        servicio = "hogar" if "hogar" in nombre else "movil" if "movil" in nombre else "general"
    elif nombre.startswith("manual"):
        tipo, servicio = "manual", "hogar"
    elif nombre.startswith("faq"):
        tipo, servicio = "faq", "general"
    else:
        tipo, servicio = "documento", "general"
    return Identidad(doc_id=_slug(base), tipo=tipo, servicio=servicio, formato=formato, fuente=ruta.name)


def detectar_version(texto: str, nombre_archivo: str) -> str | None:
    """Versión declarada en el contenido ("Versión 2.0") o, si no, en el nombre (_v2)."""
    m = _VERSION_TEXTO.search(texto[:4000])
    if m:
        return normalizar_version(m.group(1))
    m = _VERSION_NOMBRE.search(Path(nombre_archivo).stem)
    return normalizar_version(m.group(1)) if m else None


def normalizar_version(v: str) -> str:
    return v if "." in v else f"{v}.0"


def version_tupla(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", v)) or (0,)


def siguiente_version(v: str) -> str:
    return f"{version_tupla(v)[0] + 1}.0"


def detectar_codigo(texto: str) -> str | None:
    m = _CODIGO.search(texto[:4000])
    return m.group(1) if m else None


def detectar_vigente_desde(texto: str) -> str | None:
    m = _VIGENTE_DESDE.search(texto[:4000])
    if not m:
        return None
    dia, mes, anio = (int(x) for x in m.groups())
    try:
        return date(anio, mes, dia).isoformat()
    except ValueError:
        return None
