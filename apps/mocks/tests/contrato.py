"""Validación de respuestas contra una especificación OpenAPI 3.0.

- Resuelve $ref locales y traduce `nullable: true` a JSON Schema.
- Si un objeto no declara `required`, se exigen TODAS sus propiedades: el mock debe devolver la ficha
  completa (si no, un `{}` pasaría el contrato). Se permiten propiedades adicionales (extensiones).
- Verifica que el código de estado esté declarado para la operación y las cabeceras (Retry-After).
"""

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml
from jsonschema import Draft202012Validator

_IGNORAR = {"nullable", "example", "description", "$ref"}


class Contrato:
    def __init__(self, ruta: Path):
        self.spec: dict[str, Any] = yaml.safe_load(ruta.read_text(encoding="utf-8"))
        self.base = urlparse(self.spec["servers"][0]["url"]).path.rstrip("/")

    def _resolver(self, nodo: dict[str, Any]) -> dict[str, Any]:
        while "$ref" in nodo:
            destino: Any = self.spec
            for parte in nodo["$ref"].removeprefix("#/").split("/"):
                destino = destino[parte]
            nodo = destino
        return nodo

    def esquema(self, nodo: dict[str, Any]) -> dict[str, Any]:
        nodo = self._resolver(nodo)
        out = {k: v for k, v in nodo.items() if k not in _IGNORAR}
        if "properties" in nodo:
            out["properties"] = {k: self.esquema(v) for k, v in nodo["properties"].items()}
            out.setdefault("required", list(nodo["properties"]))
        if "items" in nodo:
            out["items"] = self.esquema(nodo["items"])
        if nodo.get("nullable"):
            out["type"] = [nodo["type"], "null"]
            if "enum" in out:
                out["enum"] = [*out["enum"], None]
        return out

    def operaciones(self) -> set[tuple[str, str]]:
        return {
            (metodo.upper(), self.base + ruta)
            for ruta, ops in self.spec["paths"].items()
            for metodo in ops
            if metodo in {"get", "post", "put", "patch", "delete"}
        }

    def _validar_json(self, cuerpo: Any, esquema: dict[str, Any]) -> None:
        validador = Draft202012Validator(esquema, format_checker=Draft202012Validator.FORMAT_CHECKER)
        errores = sorted(validador.iter_errors(cuerpo), key=lambda e: list(e.path))
        assert not errores, "\n".join(f"{list(e.path)}: {e.message}" for e in errores[:10])

    def validar(self, metodo: str, plantilla: str, response: httpx.Response) -> Any:
        """Valida la respuesta contra la operación `metodo plantilla` (plantilla sin el prefijo /v1)."""
        op = self.spec["paths"][plantilla][metodo.lower()]
        estado = str(response.status_code)
        declarados = list(op["responses"])
        assert estado in declarados, (
            f"{metodo} {plantilla} devolvió {estado}; el contrato declara {declarados}"
        )
        declarada = self._resolver(op["responses"][estado])
        for cabecera, definicion in declarada.get("headers", {}).items():
            assert cabecera in response.headers, f"Falta la cabecera {cabecera}"
            if definicion.get("schema", {}).get("type") == "integer":
                int(response.headers[cabecera])
        contenido = declarada.get("content", {}).get("application/json")
        if contenido is None:
            return response.json() if response.content else None
        cuerpo = response.json()
        self._validar_json(cuerpo, self.esquema(contenido["schema"]))
        return cuerpo

    def validar_error(self, response: httpx.Response, codigo: str | None = None) -> dict[str, Any]:
        """Valida contra components.schemas.Error (para estados que la operación no declara, ej. 400)."""
        cuerpo = response.json()
        esquema = self.esquema({"$ref": "#/components/schemas/Error"})
        esquema["required"] = ["codigo", "mensaje", "trace_id"]  # el mock siempre envía trace_id
        self._validar_json(cuerpo, esquema)
        if codigo:
            assert cuerpo["codigo"] == codigo, cuerpo
        return cuerpo
