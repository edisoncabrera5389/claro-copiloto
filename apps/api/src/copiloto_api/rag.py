"""Retriever híbrido: denso (embeddings) + BM25 (mismo tokenizador que la ingesta) con fusión RRF,
filtro de vigencia y reranking opcional con cross-encoder multilingüe local (fastembed, ONNX)."""

import asyncio
import math
from dataclasses import dataclass
from typing import Any, Protocol

from copiloto_api import dispersos
from copiloto_api.config import Settings


@dataclass
class Fragmento:
    id: str
    doc_id: str
    titulo: str
    version: str
    seccion: str | None
    fuente: str
    pagina: int | None
    tipo: str
    texto: str
    score_fusion: float
    score_denso: float = 0.0
    score_rerank: float | None = None

    @property
    def relevancia(self) -> float:
        """0–1 absoluta (umbral de confianza): sigmoide del reranker si está activo; si no, coseno de
        embeddings. El puntaje RRF NO sirve: depende solo de la posición (el 1.º siempre parece bueno)."""
        if self.score_rerank is not None:
            return 1 / (1 + math.exp(-self.score_rerank))
        return max(0.0, min(1.0, self.score_denso))

    def cita(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "titulo": self.titulo,
            "version": self.version,
            "seccion": self.seccion,
            "fuente": self.fuente,
            "pagina": self.pagina,
            "relevancia": round(self.relevancia, 3),
        }


class Reranker(Protocol):
    def puntuar(self, consulta: str, textos: list[str]) -> list[float]: ...


class RerankerFastembed:
    def __init__(self, modelo: str, cache_dir: str):
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self._m = TextCrossEncoder(model_name=modelo, cache_dir=cache_dir)

    def puntuar(self, consulta: str, textos: list[str]) -> list[float]:
        return list(self._m.rerank(consulta, textos))


class Retriever:
    def __init__(self, s: Settings, qdrant: Any, embedder: Any, reranker: Reranker | None = None):
        self.s, self.q, self.embedder, self.reranker = s, qdrant, embedder, reranker

    def _consultar(
        self, vector: list[float], consulta: str, incluir_transcripciones: bool
    ) -> list[Fragmento]:
        from qdrant_client import models

        must = [models.FieldCondition(key="vigente", match=models.MatchValue(value=True))]
        must_not = (
            []
            if incluir_transcripciones
            else [models.FieldCondition(key="tipo", match=models.MatchValue(value="transcripcion"))]
        )
        filtro = models.Filter(must=must, must_not=must_not)
        indices, valores = dispersos.vector_consulta(consulta)
        r = self.q.query_points(
            self.s.coleccion,
            prefetch=[
                models.Prefetch(query=vector, using="denso", limit=self.s.k_candidatos, filter=filtro),
                models.Prefetch(
                    query=models.SparseVector(indices=indices, values=valores),
                    using="bm25",
                    limit=self.s.k_candidatos,
                    filter=filtro,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=self.s.k_candidatos,
            with_payload=True,
            with_vectors=["denso"],
        )
        return [
            Fragmento(
                id=str(p.id),
                doc_id=p.payload["doc_id"],
                titulo=p.payload.get("titulo", ""),
                version=p.payload["version"],
                seccion=p.payload.get("seccion"),
                fuente=p.payload["fuente"],
                pagina=p.payload.get("pagina"),
                tipo=p.payload.get("tipo", ""),
                texto=p.payload["texto"],
                score_fusion=float(p.score),
                score_denso=_coseno(vector, (p.vector or {}).get("denso")),
            )
            for p in r.points
        ]

    async def buscar(
        self, consulta: str, k: int | None = None, incluir_transcripciones: bool = False
    ) -> list[Fragmento]:
        k = k or self.s.k_final
        vector = await self.embedder.embed(consulta)
        candidatos = await asyncio.to_thread(self._consultar, vector, consulta, incluir_transcripciones)
        if self.reranker and candidatos:
            # Solo los mejores de la fusión: en CPU el cross-encoder cuesta ~0,2 s por candidato.
            top = candidatos[: self.s.k_rerank]
            textos = [f"{c.titulo} — {c.seccion or ''}\n{c.texto}"[:1200] for c in top]
            puntajes = await asyncio.to_thread(self.reranker.puntuar, consulta, textos)
            for c, p in zip(top, puntajes, strict=True):
                c.score_rerank = float(p)
            candidatos = sorted(top, key=lambda c: c.score_rerank or 0.0, reverse=True)
        return candidatos[:k]


def _coseno(a: list[float], b: list[float] | None) -> float:
    if not b:
        return 0.0
    num = sum(x * y for x, y in zip(a, b, strict=False))
    den = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return num / den if den else 0.0
