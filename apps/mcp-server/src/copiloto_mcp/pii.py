"""Protección de datos personales (Ley 1581).

- `filtrar`: quita de las respuestas de los sistemas los campos personales antes de que lleguen al LLM.
- `redactar_texto`: enmascara documento, celular y correo en textos libres que se escriben en los
  sistemas (descripción de tickets, motivo de ajustes), porque terminan en notas e historiales.
"""

import re
from typing import Any

CAMPOS_PII = frozenset({"numero_documento", "celular", "email"})

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Celular colombiano: 3xx xxx xxxx con separadores opcionales, con o sin +57.
_CELULAR = re.compile(r"(?<!\d)(?:\+?57[\s-]?)?3\d{2}[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
# Documento: 6 a 10 dígitos seguidos o con puntos de miles (1.234.567). No precedido por letras,
# guion o $ para no tocar montos ($150.000), IDs (TK-990001, C-1004) ni fechas.
_DOCUMENTO = re.compile(r"(?<![\w$.,-])(?:\d{1,3}(?:\.\d{3}){2,3}|\d{6,10})(?![\w.,]?\d)")


def filtrar(dato: Any) -> Any:
    """Copia del dato sin los campos personales, a cualquier profundidad."""
    if isinstance(dato, dict):
        return {k: filtrar(v) for k, v in dato.items() if k not in CAMPOS_PII}
    if isinstance(dato, list):
        return [filtrar(v) for v in dato]
    return dato


def redactar_texto(texto: str) -> str:
    """Enmascara correos, celulares y números de documento. Es idempotente."""
    texto = _EMAIL.sub("[CORREO]", texto)
    texto = _CELULAR.sub("[CELULAR]", texto)
    return _DOCUMENTO.sub("[DOCUMENTO]", texto)
