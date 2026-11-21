"""Índice híbrido en Qdrant: vector denso + disperso BM25 (IDF en el servidor), filtros por payload."""

import uuid
from typing import Any

from qdrant_client import QdrantClient, models

from ingesta import dispersos
from ingesta.embeddings import Embedder

_NS = uuid.UUID("6f1c2a4e-9b7d-4c1e-8a2f-3d5e7c9b1a20")
CAMPOS_INDEXADOS = {
    "doc_id": "keyword",
    "version": "keyword",
    "tipo": "keyword",
    "servicio": "keyword",
    "vigente": "bool",
}


def id_punto(doc_id: str, version: str, orden: int) -> str:
    return str(uuid.uuid5(_NS, f"{doc_id}|{version}|{orden}"))


def _filtro(doc_id: str, version: str | None = None, excluir_version: bool = False) -> models.Filter:
    must: list[Any] = [models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
    if version is not None:
        cond = models.FieldCondition(key="version", match=models.MatchValue(value=version))
        return (
            models.Filter(must=must, must_not=[cond])
            if excluir_version
            else models.Filter(must=[*must, cond])
        )
    return models.Filter(must=must)


class IndiceQdrant:
    def __init__(self, cliente: QdrantClient, coleccion: str, dim: int):
        self.cliente, self.coleccion, self.dim = cliente, coleccion, dim

    def asegurar(self) -> None:
        if not self.cliente.collection_exists(self.coleccion):
            self.cliente.create_collection(
                self.coleccion,
                vectors_config={"denso": models.VectorParams(size=self.dim, distance=models.Distance.COSINE)},
                sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
            )
        for campo, tipo in CAMPOS_INDEXADOS.items():
            self.cliente.create_payload_index(self.coleccion, campo, field_schema=tipo)

    def reemplazar_version(self, doc_id: str, version: str, puntos: list[models.PointStruct]) -> None:
        """Idempotente: reindexar la misma versión borra sus fragmentos previos."""
        self.cliente.delete(
            self.coleccion, points_selector=models.FilterSelector(filter=_filtro(doc_id, version))
        )
        if puntos:
            self.cliente.upsert(self.coleccion, points=puntos, wait=True)

    def marcar_vigencia(self, doc_id: str, version_vigente: str) -> None:
        """La versión vigente queda vigente=true; todas las demás del documento, false."""
        self.cliente.set_payload(
            self.coleccion,
            payload={"vigente": False},
            points=_filtro(doc_id, version_vigente, excluir_version=True),
        )
        self.cliente.set_payload(
            self.coleccion, payload={"vigente": True}, points=_filtro(doc_id, version_vigente)
        )

    def contar(self, **igual: Any) -> int:
        must = [models.FieldCondition(key=k, match=models.MatchValue(value=v)) for k, v in igual.items()]
        return self.cliente.count(self.coleccion, count_filter=models.Filter(must=must), exact=True).count

    def buscar(
        self,
        consulta: str,
        embedder: Embedder,
        k: int = 5,
        solo_vigentes: bool = True,
        incluir_transcripciones: bool = False,
        prefetch: int = 20,
    ) -> list[dict[str, Any]]:
        """Híbrida: top-N denso + top-N BM25 fusionados con RRF, filtrando vigencia y tipo."""
        must: list[Any] = []
        must_not: list[Any] = []
        if solo_vigentes:
            must.append(models.FieldCondition(key="vigente", match=models.MatchValue(value=True)))
        if not incluir_transcripciones:
            must_not.append(models.FieldCondition(key="tipo", match=models.MatchValue(value="transcripcion")))
        filtro = models.Filter(must=must, must_not=must_not)
        indices, valores = dispersos.vector_consulta(consulta)
        r = self.cliente.query_points(
            self.coleccion,
            prefetch=[
                models.Prefetch(
                    query=embedder.embed([consulta])[0], using="denso", limit=prefetch, filter=filtro
                ),
                models.Prefetch(
                    query=models.SparseVector(indices=indices, values=valores),
                    using="bm25",
                    limit=prefetch,
                    filter=filtro,
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=k,
            with_payload=True,
        )
        return [{"score": round(p.score, 4), **(p.payload or {})} for p in r.points]
