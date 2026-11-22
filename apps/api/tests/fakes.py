"""Dobles de prueba: LLM con guion, retriever, MCP (que verifica tokens como el real) y dependencias."""

import json
from collections.abc import Callable
from typing import Any

import fakeredis
import mongomock

from copiloto_api.config import Settings
from copiloto_api.confirmacion import Confirmaciones, ConfirmacionInvalida, huella
from copiloto_api.llm import Respuesta, Uso
from copiloto_api.main import Dependencias
from copiloto_api.memoria import Memoria
from copiloto_api.rag import Fragmento

SECRETO = "secreto-de-pruebas-de-la-api-con-mas-de-32-caracteres"
PASSWORD = "clave-demo-123"


def settings(**cambios: Any) -> Settings:
    valores = {
        "jwt_secret": "jwt-secreto-de-pruebas-con-mas-de-32-caracteres",
        "demo_password": PASSWORD,
        "llm_api_key": "sk-prueba",
        "confirmacion_secret": SECRETO,
        "reranker_activo": False,
    }
    valores.update(cambios)
    return Settings(**valores)


def fragmento(
    n: int, texto: str, fuente: str = "Politica.docx", relevancia: float = 0.8, **kw: Any
) -> Fragmento:
    datos = {
        "id": f"p{n}",
        "doc_id": fuente.split(".")[0].lower(),
        "titulo": "Título",
        "version": "1.0",
        "seccion": f"{n}. Sección",
        "fuente": fuente,
        "pagina": None,
        "tipo": "politica",
        "texto": texto,
        "score_fusion": 0.5,
        "score_denso": relevancia,
    }
    datos.update(kw)
    return Fragmento(**datos)


class FakeLLM:
    """`guion`: lista de Respuesta (o funciones mensajes→Respuesta) para las llamadas del agente, en orden.
    La clasificación (json_mode) responde con `clasificacion`."""

    def __init__(self, guion: list[Any] | None = None, clasificacion: dict[str, Any] | None = None):
        self.guion = list(guion or [])
        self.clasificacion = clasificacion or {
            "intencion": "consulta_planes",
            "confianza": 0.9,
            "fuera_de_alcance": False,
        }
        self.llamadas: list[dict[str, Any]] = []

    async def embed(self, texto: str) -> list[float]:
        return [1.0, 0.0, 0.0]

    async def chat(
        self, modelo, mensajes, uso: Uso, tools=None, al_token=None, json_mode=False, temperatura=0.1
    ):
        self.llamadas.append(
            {
                "modelo": modelo,
                "mensajes": json.loads(json.dumps(mensajes, default=str)),
                "tools": [t["function"]["name"] for t in tools or []],
                "json": json_mode,
            }
        )
        uso.sumar(modelo, 100, 20, (1.0, 2.0))
        if json_mode:
            return Respuesta(json.dumps(self.clasificacion), [])
        paso = self.guion.pop(0) if self.guion else Respuesta("Respuesta por defecto [1].", [])
        r = paso(mensajes) if callable(paso) else paso
        if al_token and r.contenido:
            for parte in r.contenido.split(" "):
                await al_token(parte + " ")
        return r


def llamada(nombre: str, **args: Any) -> Respuesta:
    return Respuesta("", [{"id": f"c_{nombre}", "nombre": nombre, "argumentos": args}])


class FakeRetriever:
    def __init__(self, fragmentos: list[Fragmento] | None = None):
        self.fragmentos = (
            fragmentos if fragmentos is not None else [fragmento(1, "Hogar Fibra 500 cuesta $109.900.")]
        )
        self.consultas: list[str] = []
        self.reranker = None

    async def buscar(self, consulta: str, k: int | None = None, incluir_transcripciones: bool = False):
        self.consultas.append(consulta)
        return list(self.fragmentos)


ESQUEMA_ESCRITURA = {
    "type": "object",
    "properties": {"cliente_id": {"type": "string"}, "token_confirmacion": {"type": "string"}},
    "required": ["cliente_id"],
}


class FakeMCP:
    """Imita al servidor MCP: escrituras sin token → propuesta; con token → verificación real del HMAC."""

    def __init__(self, respuestas: dict[str, Callable[[dict[str, Any]], Any]] | None = None):
        self.respuestas = respuestas or {}
        self.llamadas: list[tuple[str, dict[str, Any]]] = []
        self.conf = Confirmaciones(SECRETO, 300)

    async def herramientas(self) -> list[dict[str, Any]]:
        lectura = [
            {
                "nombre": n,
                "descripcion": n,
                "esquema": {"type": "object", "properties": {}},
                "escritura": False,
            }
            for n in ("buscarCliente", "obtenerCliente", "listarTickets", "obtenerSaldo", "evaluarRetencion")
        ]
        escritura = [
            {"nombre": n, "descripcion": n, "esquema": ESQUEMA_ESCRITURA, "escritura": True}
            for n in ("crearTicket", "registrarOfertaRetencion", "aplicarAjuste")
        ]
        return lectura + escritura

    async def llamar(self, nombre: str, argumentos: dict[str, Any]) -> tuple[bool, Any, str | None]:
        self.llamadas.append((nombre, dict(argumentos)))
        if nombre in ("crearTicket", "registrarOfertaRetencion", "aplicarAjuste"):
            token = argumentos.pop("token_confirmacion", None)
            parametros = dict(argumentos)
            if not token:
                rol = "supervisor" if argumentos.get("valor", 0) > 50_000 else "asesor"
                return (
                    True,
                    {
                        "estado": "requiere_confirmacion",
                        "accion": nombre,
                        "parametros": parametros,
                        "huella": huella(nombre, parametros),
                        "requiere_rol": rol,
                        "resumen": f"{nombre} para {argumentos.get('cliente_id')}",
                    },
                    None,
                )
            try:
                c = self.conf.verificar(token, nombre, parametros)
            except ConfirmacionInvalida as e:
                return False, None, f"{e.codigo}: {e.mensaje}"
            self.conf.consumir(c)
            if nombre in self.respuestas:
                return self.respuestas[nombre](argumentos)
            return True, {"estado": "ejecutada", "confirmada_por": c.asesor_id, "rol": c.rol}, None
        if nombre in self.respuestas:
            return self.respuestas[nombre](argumentos)
        return True, {"ok": nombre}, None


class FakeML:
    """ml-service simulado. `intencion=None` imita el servicio caído (el cliente real devuelve None)."""

    def __init__(self, intencion: dict[str, Any] | None = None, churn: dict[str, Any] | None = None):
        self.respuesta_intencion = intencion
        self.respuesta_churn = churn
        self.textos: list[str] = []
        self.fichas: list[dict[str, Any]] = []

    async def intencion(self, texto: str) -> dict[str, Any] | None:
        self.textos.append(texto)
        return self.respuesta_intencion

    async def churn(self, ficha: dict[str, Any]) -> dict[str, Any] | None:
        self.fichas.append(ficha)
        return self.respuesta_churn


def dependencias(
    llm: FakeLLM | None = None,
    retriever: FakeRetriever | None = None,
    mcp: FakeMCP | None = None,
    s: Settings | None = None,
    ml: FakeML | None = None,
) -> Dependencias:
    s = s or settings()
    memoria = Memoria(s, fakeredis.FakeAsyncRedis(decode_responses=True), mongomock.MongoClient()["copiloto"])
    return Dependencias(
        llm or FakeLLM(), retriever or FakeRetriever(), mcp or FakeMCP(), memoria, ml or FakeML()
    )
