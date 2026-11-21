"""Embeddings densos detrás de una interfaz (sin lock-in: OPENAI_BASE_URL puede apuntar a LiteLLM)."""

import hashlib
import math
import re
from typing import Protocol


class Embedder(Protocol):
    nombre: str
    dim: int

    def embed(self, textos: list[str]) -> list[list[float]]: ...


class OpenAIEmbedder:
    def __init__(self, api_key: str, modelo: str, dim: int, base_url: str | None = None, lote: int = 64):
        from openai import OpenAI

        self._cliente = OpenAI(api_key=api_key, base_url=base_url, timeout=30, max_retries=4)
        self.nombre, self.dim, self._lote = modelo, dim, lote

    def embed(self, textos: list[str]) -> list[list[float]]:
        vectores: list[list[float]] = []
        for i in range(0, len(textos), self._lote):  # el SDK reintenta 429/5xx con backoff
            r = self._cliente.embeddings.create(model=self.nombre, input=textos[i : i + self._lote])
            vectores += [d.embedding for d in sorted(r.data, key=lambda d: d.index)]
        return vectores


class EmbedderDeterminista:
    """Sin red ni costo: bolsa de palabras con hashing. Para pruebas y modo offline (no para producción)."""

    def __init__(self, dim: int = 256):
        self.nombre, self.dim = f"hashing-{dim}", dim

    def embed(self, textos: list[str]) -> list[list[float]]:
        salida = []
        for t in textos:
            v = [0.0] * self.dim
            for palabra in re.findall(r"\w+", t.lower()):
                h = int(hashlib.md5(palabra.encode(), usedforsecurity=False).hexdigest(), 16)
                v[h % self.dim] += 1.0 if (h >> 8) % 2 else -1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            salida.append([x / n for x in v])
        return salida
