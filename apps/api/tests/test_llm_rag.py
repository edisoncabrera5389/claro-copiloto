from types import SimpleNamespace as NS

from qdrant_client import QdrantClient, models

from copiloto_api import dispersos
from copiloto_api.llm import ClienteLLM, Uso
from copiloto_api.rag import Retriever

from .fakes import settings


def chunk(contenido=None, tool=None, usage=None):
    delta = NS(content=contenido, tool_calls=[tool] if tool else None)
    return NS(choices=[NS(delta=delta)] if (contenido or tool) else [], usage=usage)


class OpenAIFalso:
    def __init__(self, chunks):
        self.chunks = chunks
        self.kwargs = None
        self.chat = NS(completions=NS(create=self._create))
        self.embeddings = NS(create=self._emb)

    async def _create(self, **kwargs):
        self.kwargs = kwargs

        async def gen():
            for c in self.chunks:
                yield c

        return gen()

    async def _emb(self, model, input):  # noqa: A002
        return NS(data=[NS(embedding=[0.1, 0.2])])


async def test_streaming_arma_tool_calls_por_fragmentos_y_calcula_costo():
    tc1 = NS(index=0, id="call_1", function=NS(name="buscar_", arguments='{"consulta": "LO'))
    tc2 = NS(index=0, id=None, function=NS(name="conocimiento", arguments='S rojo"}'))
    falso = OpenAIFalso(
        [chunk(tool=tc1), chunk(tool=tc2), chunk(usage=NS(prompt_tokens=1000, completion_tokens=500))]
    )
    s = settings()
    uso = Uso()
    r = await ClienteLLM(s, falso).chat(
        s.modelo_economico, [{"role": "user", "content": "x"}], uso, tools=[{"t": 1}]
    )
    assert r.tool_calls == [
        {"id": "call_1", "nombre": "buscar_conocimiento", "argumentos": {"consulta": "LOS rojo"}}
    ]
    assert uso.costo_usd == (1000 * 0.40 + 500 * 1.60) / 1_000_000 and uso.modelos == ["economico"]
    assert falso.kwargs["stream_options"] == {"include_usage": True}


async def test_tokens_de_texto_se_entregan_en_vivo_y_json_mode():
    falso = OpenAIFalso(
        [
            chunk("Hola "),
            chunk("asesor"),
            chunk(tool=NS(index=0, id="c", function=NS(name="x", arguments="{mal"))),
        ]
    )
    vistos = []

    async def al_token(t):
        vistos.append(t)

    r = await ClienteLLM(settings(), falso).chat("alto", [], Uso(), al_token=al_token, json_mode=True)
    assert vistos == ["Hola ", "asesor"] and r.contenido == "Hola asesor"
    assert r.tool_calls[0]["argumentos"] == {"_error": "argumentos no son JSON válido"}
    assert falso.kwargs["response_format"] == {"type": "json_object"}
    assert await ClienteLLM(settings(), falso).embed("x") == [0.1, 0.2]


class Embedder:
    async def embed(self, texto):
        return [1.0, 0.0, 0.0]


def qdrant_con_datos():
    q = QdrantClient(":memory:")
    q.create_collection(
        "conocimiento",
        vectors_config={"denso": models.VectorParams(size=3, distance=models.Distance.COSINE)},
        sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    puntos = []
    for i, (texto, vigente, tipo, vec) in enumerate(
        [
            ("Error E-202 refrescar señal", True, "manual", [1, 0, 0]),
            ("Catálogo viejo E-202", False, "catalogo", [1, 0, 0]),
            ("Cliente dijo E-202 en la llamada", True, "transcripcion", [1, 0, 0]),
            ("Otro tema sin relación", True, "faq", [0, 1, 0]),
        ]
    ):
        idx, val = dispersos.vector_documento(texto)
        puntos.append(
            models.PointStruct(
                id=i + 1,
                vector={"denso": vec, "bm25": models.SparseVector(indices=idx, values=val)},
                payload={
                    "doc_id": f"d{i}",
                    "titulo": "T",
                    "version": "1.0",
                    "seccion": "S",
                    "fuente": f"f{i}.pdf",
                    "tipo": tipo,
                    "vigente": vigente,
                    "texto": texto,
                },
            )
        )
    q.upsert("conocimiento", puntos)
    return q


async def test_retriever_filtra_vigencia_y_transcripciones_con_relevancia_coseno():
    r = Retriever(settings(k_final=5), qdrant_con_datos(), Embedder())
    frags = await r.buscar("error E-202")
    assert [f.fuente for f in frags][0] == "f0.pdf"
    assert {f.fuente for f in frags} == {"f0.pdf", "f3.pdf"}  # sin el no vigente ni la transcripción
    assert frags[0].relevancia > 0.99 and next(f for f in frags if f.fuente == "f3.pdf").relevancia < 0.01
    con_trx = await r.buscar("error E-202", incluir_transcripciones=True)
    assert "f2.pdf" in {f.fuente for f in con_trx}


async def test_reranker_reordena_los_mejores():
    class Reranker:
        def puntuar(self, consulta, textos):
            return [5.0 if "Otro" in t else -5.0 for t in textos]

    r = Retriever(settings(k_rerank=10), qdrant_con_datos(), Embedder(), Reranker())
    frags = await r.buscar("error E-202", k=2)
    assert (
        frags[0].fuente == "f3.pdf" and frags[0].relevancia > 0.99 and frags[0].cita()["relevancia"] == 0.993
    )
