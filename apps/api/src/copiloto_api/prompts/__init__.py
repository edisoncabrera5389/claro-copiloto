"""Prompts versionados (semver). La versión de cada prompt queda en la auditoría de cada turno."""

from dataclasses import dataclass
from functools import cache
from importlib import resources

import yaml


@dataclass(frozen=True)
class Prompt:
    nombre: str
    version: str
    texto: str

    def render(self, **valores: str) -> str:
        return self.texto.format(**valores)


@cache
def cargar(nombre: str) -> Prompt:
    datos = yaml.safe_load(
        resources.files("copiloto_api.prompts").joinpath(f"{nombre}.yaml").read_text("utf-8")
    )
    return Prompt(datos["nombre"], str(datos["version"]), datos["texto"])


def versiones() -> dict[str, str]:
    return {n: cargar(n).version for n in ("sistema", "clasificador", "alcance")}
