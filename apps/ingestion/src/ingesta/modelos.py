"""Estructuras que viajan por el pipeline."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Identidad:
    """Quién es el archivo, según su nombre y extensión."""

    doc_id: str  # id lógico estable entre versiones y formatos (ej. catalogo_planes_claro_2026)
    tipo: str  # catalogo, politica, contrato, manual, faq, correo, transcripcion, documento
    servicio: str  # hogar, movil, general
    formato: str  # pdf, docx, md, eml, txt, wav
    fuente: str  # nombre del archivo original (lo que se cita)


@dataclass
class Bloque:
    """Unidad estructural extraída: una sección de texto o una tabla."""

    texto: str
    seccion: str | None = None
    pagina: int | None = None
    es_tabla: bool = False


@dataclass
class DocumentoExtraido:
    bloques: list[Bloque]
    titulo: str | None = None
    metadatos: dict[str, Any] = field(default_factory=dict)
    texto_cabecera: str = ""  # primeras líneas crudas (para detectar versión y código aunque se limpien)

    @property
    def texto(self) -> str:
        return "\n\n".join(b.texto for b in self.bloques)


@dataclass
class Fragmento:
    texto: str
    orden: int
    seccion: str | None = None
    pagina: int | None = None
    es_tabla: bool = False
