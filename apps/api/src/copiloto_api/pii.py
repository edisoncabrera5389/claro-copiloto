"""PII en el chat (Ley 1581): lo que escribe el asesor no llega completo al LLM.

`Boveda` reemplaza documento, celular y correo por marcadores (<DOCUMENTO_1>) antes del LLM y los
restituye SOLO al llamar una tool (ej. buscarCliente necesita el documento real). Así el LLM, el
proveedor y las trazas nunca ven el dato, pero el flujo funciona.
"""

import re
from typing import Any

_PATRONES = [
    ("CORREO", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("CELULAR", re.compile(r"(?<!\d)(?:\+?57[\s-]?)?3\d{2}[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")),
    ("DOCUMENTO", re.compile(r"(?<![\w$.,-])(?:\d{1,3}(?:\.\d{3}){2,3}|\d{6,10})(?![\w.,]?\d)")),
]
_MARCADOR = re.compile(r"<(CORREO|CELULAR|DOCUMENTO)_\d+>")


class Boveda:
    def __init__(self, datos: dict[str, str] | None = None):
        self.datos: dict[str, str] = dict(datos or {})

    def enmascarar(self, texto: str) -> str:
        for etiqueta, rx in _PATRONES:

            def reemplazo(m: re.Match, etiqueta: str = etiqueta) -> str:
                valor = m.group(0)
                existente = next((k for k, v in self.datos.items() if v == valor), None)
                if existente:
                    return existente
                marcador = f"<{etiqueta}_{sum(k.startswith(f'<{etiqueta}_') for k in self.datos) + 1}>"
                self.datos[marcador] = valor
                return marcador

            texto = rx.sub(reemplazo, texto)
        return texto

    def restituir(self, valor: Any) -> Any:
        """Reemplaza marcadores por el dato real dentro de los argumentos de una tool."""
        if isinstance(valor, str):
            return _MARCADOR.sub(lambda m: self.datos.get(m.group(0), m.group(0)), valor)
        if isinstance(valor, dict):
            return {k: self.restituir(v) for k, v in valor.items()}
        if isinstance(valor, list):
            return [self.restituir(v) for v in valor]
        return valor


def redactar(texto: str) -> str:
    """Red de seguridad en la salida: nada con forma de documento, celular o correo llega al asesor."""
    for etiqueta, rx in _PATRONES:
        texto = rx.sub(f"[{etiqueta}]", texto)
    return texto
