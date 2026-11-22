"""Cliente del servidor MCP (HTTP streamable). Convierte las tools al formato de tool-calling del LLM."""

import copy
from contextlib import asynccontextmanager
from typing import Any

from copiloto_api.observabilidad import marcar_error, span


def a_formato_llm(herramienta: dict[str, Any]) -> dict[str, Any]:
    """El LLM nunca ve `token_confirmacion`: solo la API lo agrega cuando el asesor confirma."""
    esquema = copy.deepcopy(herramienta["esquema"])
    esquema.get("properties", {}).pop("token_confirmacion", None)
    if "required" in esquema:
        esquema["required"] = [c for c in esquema["required"] if c != "token_confirmacion"]
    return {
        "type": "function",
        "function": {
            "name": herramienta["nombre"],
            "description": herramienta["descripcion"],
            "parameters": esquema,
        },
    }


class ClienteMCP:
    def __init__(self, url: str):
        self.url = url
        self._herramientas: list[dict[str, Any]] | None = None

    @asynccontextmanager
    async def _cliente(self):
        from fastmcp import Client

        async with Client(self.url, timeout=30) as c:
            yield c

    async def herramientas(self) -> list[dict[str, Any]]:
        if self._herramientas is None:
            async with self._cliente() as c:
                self._herramientas = [
                    {
                        "nombre": t.name,
                        "descripcion": t.description or "",
                        "esquema": t.input_schema,
                        "escritura": not bool(t.annotations and t.annotations.read_only_hint),
                    }
                    for t in await c.list_tools()
                ]
        return self._herramientas

    async def llamar(self, nombre: str, argumentos: dict[str, Any]) -> tuple[bool, Any, str | None]:
        # En la traza: nombre de la tool y NOMBRES de los argumentos (los valores pueden ser PII restituida).
        argumentos_traza = sorted(k for k in argumentos if k != "token_confirmacion")
        with span(
            f"tool.{nombre}", "TOOL", **{"tool.name": nombre, "copiloto.argumentos": argumentos_traza}
        ) as s:
            async with self._cliente() as c:
                r = await c.call_tool(nombre, argumentos, raise_on_error=False)
            if r.is_error:
                error = " ".join(getattr(b, "text", "") for b in r.content)[:500]
                s.set_attribute("copiloto.error", error.split(":")[0][:80])  # solo el código
                marcar_error(s, error.split(":")[0])
                return False, None, error
            s.set_attribute("copiloto.confirmada", "token_confirmacion" in argumentos)
            return True, r.data if r.data is not None else r.structured_content, None
