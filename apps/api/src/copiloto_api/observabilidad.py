"""Observabilidad (SAD 2.10): trazas OpenTelemetry → Phoenix y métricas Prometheus.

Trazas (convenciones OpenInference, que Phoenix entiende): un span AGENT por turno, CHAIN por nodo del grafo,
RETRIEVER por búsqueda, TOOL por llamada al MCP y LLM por llamada al modelo (instrumentador de OpenAI).

PII (Ley 1581): los atributos se eligen a mano. Nunca el mensaje original (puede traer documento o celular),
ni la bóveda, ni los VALORES de los argumentos de las tools (la bóveda ya los restituyó): solo nombres,
resultados y el texto ENMASCARADO que también ve el LLM. Una prueba lo verifica sobre los spans exportados.
"""

import json
import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

log = logging.getLogger("copiloto_api")
tracer = trace.get_tracer("copiloto_api")

# Convenciones OpenInference (texto literal: evita depender de la versión del paquete de constantes)
KIND = "openinference.span.kind"
_configurado = False


def configurar_trazas(endpoint: str | None, proyecto: str, servicio: str = "copiloto-api") -> bool:
    """Exporta a Phoenix por OTLP/HTTP. Sin endpoint (pruebas, desarrollo) no hace nada."""
    global _configurado
    if not endpoint or _configurado:
        return False
    from openinference.instrumentation.openai import OpenAIInstrumentor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    proveedor = TracerProvider(
        resource=Resource.create({"service.name": servicio, "openinference.project.name": proyecto})
    )
    proveedor.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")))
    trace.set_tracer_provider(proveedor)
    # Llamadas al LLM: mensajes (ya enmascarados), tools ofrecidas, tokens y latencia por llamada.
    OpenAIInstrumentor().instrument(tracer_provider=proveedor)
    _configurado = True
    log.info(json.dumps({"evento": "trazas_activas", "destino": endpoint, "proyecto": proyecto}))
    return True


def _texto(valor: Any, limite: int = 4000) -> str:
    return (valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False, default=str))[:limite]


@contextmanager
def span(nombre: str, tipo: str, **atributos: Any) -> Iterator[Span]:
    with tracer.start_as_current_span(nombre) as s:
        s.set_attribute(KIND, tipo)
        for k, v in atributos.items():
            if v is not None:
                s.set_attribute(k, v if isinstance(v, (str, bool, int, float)) else _texto(v))
        yield s


def marcar_error(s: Span, mensaje: str) -> None:
    s.set_status(Status(StatusCode.ERROR, mensaje[:200]))


# Qué se puede anotar de la salida de cada nodo (nunca mensaje, bóveda ni historial).
_CAMPOS_NODO = (
    "ruta",
    "motivo",
    "intencion",
    "confianza_intencion",
    "origen_intencion",
    "modelo",
    "confianza",
)


def nodo(
    nombre: str, fn: Callable[[Any], Awaitable[dict[str, Any]]]
) -> Callable[[Any], Awaitable[dict[str, Any]]]:
    """Envuelve un nodo del grafo en un span CHAIN con un resumen seguro de lo que decidió."""

    async def envuelto(estado: Any) -> dict[str, Any]:
        with span(f"nodo.{nombre}", "CHAIN") as s:
            cambios = await fn(estado)
            for campo in _CAMPOS_NODO:
                if isinstance(cambios.get(campo), (str, int, float)):
                    s.set_attribute(f"copiloto.{campo}", cambios[campo])
            for lista in ("fuentes", "tools", "propuestas", "precarga"):
                if isinstance(cambios.get(lista), list):
                    s.set_attribute(f"copiloto.{lista}", len(cambios[lista]))
            return cambios

    envuelto.__name__ = nombre
    return envuelto


def documentos_recuperados(s: Span, fragmentos: list[Any]) -> None:
    """Atributos RETRIEVER: id, puntaje, fuente y versión de cada fragmento (base de conocimiento)."""
    for i, f in enumerate(fragmentos):
        base = f"retrieval.documents.{i}.document"
        s.set_attribute(f"{base}.id", f.id)
        s.set_attribute(f"{base}.score", float(f.relevancia))
        s.set_attribute(f"{base}.content", f.texto[:500])
        s.set_attribute(
            f"{base}.metadata", _texto({"fuente": f.fuente, "version": f.version, "seccion": f.seccion})
        )


# ------------------------------------------------------------------------------------- métricas ------

_BLOQUEOS = {"CLIENTE_NO_IDENTIFICADO", "LIMITE_LLAMADAS"}


class Metricas:
    """Métricas del agente (SAD 2.10: éxito de tareas, errores de tools, bucles, bloqueos, escalamientos,
    costo y latencia). Registro propio por app (las pruebas crean varias)."""

    def __init__(self) -> None:
        r = self.registro = CollectorRegistry()
        self.turnos = Counter(
            "copiloto_turnos", "Turnos atendidos", ["ruta", "intencion", "origen_intencion"], registry=r
        )
        self.errores_turno = Counter("copiloto_errores_turno", "Turnos que terminaron en error", registry=r)
        self.en_curso = Gauge("copiloto_turnos_en_curso", "Turnos en curso", registry=r)
        # Cubetas finas alrededor de las metas (2 s primer token, 8 s total): con cubetas gruesas
        # la interpolación de histogram_quantile mostraba p95 2,37 s cuando el golden medía 1,84 s.
        cubetas = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0, 4.0, 5.0, 6.5, 8.0, 13.0, 21.0)
        self.ttft = Histogram("copiloto_ttft_segundos", "Tiempo al primer token", buckets=cubetas, registry=r)
        self.duracion = Histogram(
            "copiloto_turno_segundos", "Duración total del turno", buckets=cubetas, registry=r
        )
        self.costo = Counter("copiloto_costo_usd", "Costo estimado del LLM (USD)", ["modelo"], registry=r)
        self.tokens = Counter("copiloto_tokens", "Tokens del LLM", ["tipo"], registry=r)
        self.tools = Counter("copiloto_tool_llamadas", "Llamadas a tools", ["tool", "resultado"], registry=r)
        self.bucles = Counter(
            "copiloto_bucles_cortados", "Bucles de tools cortados por el límite", registry=r
        )
        self.bloqueos = Counter(
            "copiloto_acciones_bloqueadas", "Acciones bloqueadas por política", ["motivo"], registry=r
        )
        self.escalamientos = Counter(
            "copiloto_escalamientos", "Escalamientos a supervisor", ["origen", "motivo"], registry=r
        )
        self.sin_cita = Counter("copiloto_respuestas_sin_cita", "Respuestas del agente sin cita", registry=r)
        self.feedback = Counter("copiloto_feedback", "Calificaciones del asesor", ["valor"], registry=r)
        self.acciones = Counter(
            "copiloto_acciones", "Propuestas confirmadas o rechazadas", ["accion", "resultado"], registry=r
        )
        # Series en 0 desde el arranque: un contador que aparece ya en 1 no muestra increase() en Prometheus
        # (el tablero marcaba 0 % de 👍 con un 👍 registrado).
        for valor in ("positivo", "negativo"):
            self.feedback.labels(valor)
        for motivo in ("CLIENTE_NO_IDENTIFICADO", "LIMITE_LLAMADAS", "INYECCION"):
            self.bloqueos.labels(motivo)
        self.escalamientos.labels("manual", "MANUAL")
        for accion in ("crearTicket", "registrarOfertaRetencion", "aplicarAjuste"):
            for resultado in ("ejecutada", "rechazada", "error"):
                self.acciones.labels(accion, resultado)

    def registrar_turno(self, r: dict[str, Any], origen_intencion: str | None) -> None:
        self.turnos.labels(
            r["ruta"] or "?", r.get("intencion") or "ninguna", origen_intencion or "ninguno"
        ).inc()
        self.ttft.observe(r["latencias"]["ttft_ms"] / 1000)
        self.duracion.observe(r["latencias"]["total_ms"] / 1000)
        if r["uso"]["costo_usd"]:
            self.costo.labels(r.get("modelo") or "?").inc(r["uso"]["costo_usd"])
        self.tokens.labels("entrada").inc(r["uso"]["tokens_entrada"])
        self.tokens.labels("salida").inc(r["uso"]["tokens_salida"])
        for t in r.get("tools", []):
            error = (t.get("error") or "").split(":")[0]
            resultado = "ok" if t["ok"] else ("bloqueada" if error in _BLOQUEOS else "error")
            self.tools.labels(t["nombre"], resultado).inc()
            if error in _BLOQUEOS:
                self.bloqueos.labels(error).inc()
        self.bucles.inc(sum(1 for a in r.get("advertencias", []) if a.startswith("bucle cortado")))
        if r["ruta"] == "bloqueado":
            self.bloqueos.labels("INYECCION").inc()
        if r["ruta"] == "escalar":
            self.escalamientos.labels("politica", r.get("motivo") or "?").inc()
        if r.get("sin_cita"):
            self.sin_cita.inc()
