"""Cliente del LLM Gateway (LiteLLM) en formato OpenAI: streaming con tool-calls, uso y costo."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from copiloto_api.config import Settings


@dataclass
class Uso:
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo_usd: float = 0.0
    llamadas: int = 0
    modelos: list[str] = field(default_factory=list)

    def sumar(self, modelo: str, entrada: int, salida: int, precios: tuple[float, float]) -> None:
        self.tokens_entrada += entrada
        self.tokens_salida += salida
        self.costo_usd += (entrada * precios[0] + salida * precios[1]) / 1_000_000
        self.llamadas += 1
        if modelo not in self.modelos:
            self.modelos.append(modelo)

    def dict(self) -> dict[str, Any]:
        return {
            "tokens_entrada": self.tokens_entrada,
            "tokens_salida": self.tokens_salida,
            "costo_usd": round(self.costo_usd, 6),
            "llamadas": self.llamadas,
            "modelos": self.modelos,
        }


@dataclass
class Respuesta:
    contenido: str
    tool_calls: list[dict[str, Any]]  # [{"id", "nombre", "argumentos": dict}]


class ClienteLLM:
    def __init__(self, s: Settings, cliente: Any = None):
        if cliente is None:
            from openai import AsyncOpenAI

            cliente = AsyncOpenAI(
                base_url=s.llm_base_url, api_key=s.llm_api_key.get_secret_value(), timeout=60, max_retries=1
            )  # los reintentos y el fallback los hace LiteLLM
        self._c, self.s = cliente, s
        self._precios = {
            s.modelo_economico: (s.precio_entrada_economico, s.precio_salida_economico),
            s.modelo_alto: (s.precio_entrada_alto, s.precio_salida_alto),
        }

    async def embed(self, texto: str) -> list[float]:
        r = await self._c.embeddings.create(model=self.s.modelo_embedding, input=[texto])
        return r.data[0].embedding

    async def chat(
        self,
        modelo: str,
        mensajes: list[dict[str, Any]],
        uso: Uso,
        tools: list[dict[str, Any]] | None = None,
        al_token: Callable[[str], Awaitable[None]] | None = None,
        json_mode: bool = False,
        temperatura: float = 0.1,
    ) -> Respuesta:
        """Streaming: cada fragmento de texto se entrega a `al_token` apenas llega (TTFT bajo)."""
        kwargs: dict[str, Any] = {
            "model": modelo,
            "messages": mensajes,
            "temperature": temperatura,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        stream = await self._c.chat.completions.create(**kwargs)
        texto: list[str] = []
        llamadas: dict[int, dict[str, str]] = {}
        async for chunk in stream:
            if getattr(chunk, "usage", None):
                uso.sumar(
                    modelo,
                    chunk.usage.prompt_tokens,
                    chunk.usage.completion_tokens,
                    self._precios.get(modelo, (0.0, 0.0)),
                )
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if getattr(delta, "content", None):
                texto.append(delta.content)
                if al_token:
                    await al_token(delta.content)
            for tc in getattr(delta, "tool_calls", None) or []:
                actual = llamadas.setdefault(tc.index, {"id": "", "nombre": "", "argumentos": ""})
                actual["id"] = tc.id or actual["id"]
                if tc.function and tc.function.name:
                    actual["nombre"] += tc.function.name
                if tc.function and tc.function.arguments:
                    actual["argumentos"] += tc.function.arguments
        tool_calls = []
        for i in sorted(llamadas):
            c = llamadas[i]
            try:
                args = json.loads(c["argumentos"] or "{}")
            except json.JSONDecodeError:
                args = {"_error": "argumentos no son JSON válido"}
            tool_calls.append({"id": c["id"] or f"call_{i}", "nombre": c["nombre"], "argumentos": args})
        return Respuesta("".join(texto), tool_calls)
