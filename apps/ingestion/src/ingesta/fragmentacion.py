"""Chunking por estructura: una tabla = un fragmento; textos por sección (~500 tokens, 15 % de solape)."""

import re

from ingesta.modelos import Bloque, Fragmento

_ORACIONES = re.compile(r"(?<=[.!?])\s+|\n+")


def _ventanas(texto: str, max_chars: int, solape: float) -> list[str]:
    """Parte en ventanas de hasta max_chars respetando oraciones, con solape entre ventanas."""
    if len(texto) <= max_chars:
        return [texto]
    oraciones = [o.strip() for o in _ORACIONES.split(texto) if o.strip()]
    ventanas: list[str] = []
    actual: list[str] = []
    for o in oraciones:
        if actual and len(" ".join(actual)) + len(o) + 1 > max_chars:
            ventanas.append(" ".join(actual))
            # Solape: se arrastran las últimas oraciones hasta ~solape del tamaño.
            arrastre: list[str] = []
            for previa in reversed(actual):
                if len(" ".join([previa, *arrastre])) > max_chars * solape:
                    break
                arrastre.insert(0, previa)
            actual = arrastre
        if len(o) > max_chars:  # oración gigante (raro): corte duro
            ventanas.extend(o[i : i + max_chars] for i in range(0, len(o), max_chars))
            actual = []
            continue
        actual.append(o)
    if actual:
        ventanas.append(" ".join(actual))
    return ventanas


def _partir_tabla(md: str, max_chars: int) -> list[str]:
    """Las tablas no se cortan salvo que sean enormes; si se cortan, cada parte repite el encabezado."""
    if len(md) <= max_chars * 2:
        return [md]
    lineas = md.splitlines()
    cabecera, filas = lineas[:2], lineas[2:]
    partes, actual = [], []
    for f in filas:
        if actual and len("\n".join(cabecera + actual + [f])) > max_chars:
            partes.append("\n".join(cabecera + actual))
            actual = []
        actual.append(f)
    if actual:
        partes.append("\n".join(cabecera + actual))
    return partes


def fragmentar(bloques: list[Bloque], max_chars: int = 2000, solape: float = 0.15) -> list[Fragmento]:
    fragmentos: list[Fragmento] = []
    for b in bloques:
        textos = _partir_tabla(b.texto, max_chars) if b.es_tabla else _ventanas(b.texto, max_chars, solape)
        for t in textos:
            if t.strip():
                fragmentos.append(Fragmento(t.strip(), len(fragmentos), b.seccion, b.pagina, b.es_tabla))
    return fragmentos
