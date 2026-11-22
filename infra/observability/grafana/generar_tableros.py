"""Genera los tableros de Grafana como código (JSON provisionado, no editado a mano en la UI).

    py -3.13 infra/observability/grafana/generar_tableros.py   # → dashboards/*.json
"""

import json
from pathlib import Path

DS = {"type": "prometheus", "uid": "prometheus"}
DESTINO = Path(__file__).parent / "dashboards"


class Tablero:
    def __init__(self, uid: str, titulo: str, descripcion: str):
        self.uid, self.titulo, self.descripcion = uid, titulo, descripcion
        self.paneles: list[dict] = []
        self.y = 0
        self.x = 0
        self.alto_fila = 0

    def _pos(self, w: int, h: int) -> dict:
        if self.x + w > 24:
            self.x, self.y = 0, self.y + self.alto_fila
            self.alto_fila = 0
        pos = {"x": self.x, "y": self.y, "w": w, "h": h}
        self.x += w
        self.alto_fila = max(self.alto_fila, h)
        return pos

    def fila(self, titulo: str) -> None:
        self.x, self.y = 0, self.y + self.alto_fila
        self.alto_fila = 0
        self.paneles.append({"type": "row", "title": titulo, "collapsed": False, "gridPos": self._pos(24, 1)})
        self.x, self.y, self.alto_fila = 0, self.y + 1, 0

    def panel(self, tipo: str, titulo: str, consultas: list[tuple[str, str]], w: int, h: int, **extra) -> None:
        unidad = extra.pop("unidad", None)
        umbrales = extra.pop("umbrales", None)
        decimales = extra.pop("decimales", None)
        descripcion = extra.pop("descripcion", "")
        defaults: dict = {"custom": extra.pop("custom", {})}
        if unidad:
            defaults["unit"] = unidad
        if decimales is not None:
            defaults["decimals"] = decimales
        if umbrales:
            defaults["thresholds"] = {
                "mode": "absolute",
                "steps": [{"color": "green", "value": None}]
                + [{"color": c, "value": v} for v, c in umbrales],
            }
            defaults["color"] = {"mode": "thresholds"}
        self.paneles.append(
            {
                "type": tipo,
                "title": titulo,
                "description": descripcion,
                "datasource": DS,
                "gridPos": self._pos(w, h),
                "targets": [
                    {"refId": chr(65 + i), "expr": expr, "legendFormat": leyenda, "datasource": DS,
                     **({"instant": True, "format": "table"} if tipo == "table" else {})}
                    for i, (expr, leyenda) in enumerate(consultas)
                ],
                "fieldConfig": {"defaults": defaults, "overrides": []},
                "options": extra.pop("opciones", {}),
                **extra,
            }
        )

    def stat(self, titulo: str, expr: str, w: int = 3, **kw) -> None:
        kw.setdefault("opciones", {"reduceOptions": {"calcs": ["lastNotNull"]}, "colorMode": "background",
                                   "graphMode": "none", "textMode": "value"})
        self.panel("stat", titulo, [(expr, "")], w, 4, **kw)

    def serie(self, titulo: str, consultas: list[tuple[str, str]], w: int = 12, apilado: bool = False, **kw) -> None:
        custom = {"lineWidth": 2, "fillOpacity": 20 if apilado else 5, "showPoints": "never"}
        if apilado:
            custom["stacking"] = {"mode": "normal"}
        kw.setdefault("opciones", {"legend": {"displayMode": "list", "placement": "bottom"},
                                   "tooltip": {"mode": "multi"}})
        self.panel("timeseries", titulo, consultas, w, 8, custom=custom, **kw)

    def json(self) -> dict:
        return {
            "uid": self.uid,
            "title": self.titulo,
            "description": self.descripcion,
            "tags": ["claro-copiloto"],
            "timezone": "browser",
            "schemaVersion": 41,
            "refresh": "30s",
            "time": {"from": "now-6h", "to": "now"},
            "panels": [{"id": i + 1, **p} for i, p in enumerate(self.paneles)],
            "editable": False,
        }


def agente() -> Tablero:
    t = Tablero("copiloto-agente", "Copiloto · Agente y operación",
                "KPIs del caso, monitoreo de agentes (SAD 2.10) y alertas activas. Trazas por turno en Phoenix.")
    t.fila("KPIs (24 h)")
    t.stat("Turnos", "sum(increase(copiloto_turnos_total[24h]))", decimales=0)
    t.stat("p95 primer token", "histogram_quantile(0.95, sum by (le) (rate(copiloto_ttft_segundos_bucket[1h])))",
           unidad="s", decimales=2, umbrales=[(1.5, "orange"), (2, "red")], descripcion="Meta ≤ 2 s")
    t.stat("p95 respuesta total", "histogram_quantile(0.95, sum by (le) (rate(copiloto_turno_segundos_bucket[1h])))",
           unidad="s", decimales=2, umbrales=[(6, "orange"), (8, "red")], descripcion="Meta ≤ 8 s")
    t.stat("Sin cita", "sum(increase(copiloto_respuestas_sin_cita_total[24h])) / "
           "clamp_min(sum(increase(copiloto_turnos_total{ruta=\"agente\"}[24h])), 1)",
           unidad="percentunit", decimales=1, umbrales=[(0.03, "orange"), (0.05, "red")], descripcion="Meta ≤ 5 %")
    t.stat("Éxito de tools", "sum(increase(copiloto_tool_llamadas_total{resultado=\"ok\"}[24h])) / "
           "clamp_min(sum(increase(copiloto_tool_llamadas_total[24h])), 1)",
           unidad="percentunit", decimales=1, umbrales=[(0, "red"), (0.8, "orange"), (0.9, "green")],
           descripcion="Meta de éxito de tareas ≥ 90 %")
    t.stat("👍 de los asesores", "sum(increase(copiloto_feedback_total{valor=\"positivo\"}[24h])) / "
           "clamp_min(sum(increase(copiloto_feedback_total[24h])), 1)",
           unidad="percentunit", decimales=0, umbrales=[(0, "red"), (0.7, "orange"), (0.85, "green")])
    t.stat("Costo LLM", "sum(increase(copiloto_costo_usd_total[24h]))", unidad="currencyUSD", decimales=3)
    t.stat("Acciones bloqueadas", "sum(increase(copiloto_acciones_bloqueadas_total[24h]))", decimales=0,
           umbrales=[(1, "orange"), (10, "red")], descripcion="Meta: 0 acciones no permitidas ejecutadas")

    t.fila("Tráfico y latencia")
    t.serie("Turnos por minuto según ruta", [("sum by (ruta) (rate(copiloto_turnos_total[5m])) * 60", "{{ruta}}")],
            apilado=True, unidad="short")
    t.serie("Latencia (p50 / p95)", [
        ("histogram_quantile(0.5, sum by (le) (rate(copiloto_ttft_segundos_bucket[5m])))", "primer token p50"),
        ("histogram_quantile(0.95, sum by (le) (rate(copiloto_ttft_segundos_bucket[5m])))", "primer token p95"),
        ("histogram_quantile(0.95, sum by (le) (rate(copiloto_turno_segundos_bucket[5m])))", "total p95"),
    ], unidad="s")
    t.serie("Costo por modelo (USD por hora)", [("sum by (modelo) (increase(copiloto_costo_usd_total[1h]))", "{{modelo}}")],
            unidad="currencyUSD")
    t.serie("Intención: quién decide (cascada SVM → LLM)",
            [("sum by (origen_intencion) (increase(copiloto_turnos_total[15m]))", "{{origen_intencion}}")],
            apilado=True, descripcion="svm = ml-service seguro (≥ 0,7) · llm = SVM dudoso sin cliente · reglas = con cliente")

    t.fila("Agente: tools, política y acciones")
    t.serie("Llamadas a tools por resultado", [("sum by (resultado) (increase(copiloto_tool_llamadas_total[15m]))",
                                                "{{resultado}}")], w=8, apilado=True)
    t.serie("Bloqueos y bucles", [
        ("sum by (motivo) (increase(copiloto_acciones_bloqueadas_total[15m]))", "bloqueo {{motivo}}"),
        ("increase(copiloto_bucles_cortados_total[15m])", "bucle cortado"),
    ], w=8)
    t.serie("Escalamientos a supervisor", [("sum by (origen, motivo) (increase(copiloto_escalamientos_total[15m]))",
                                            "{{origen}} · {{motivo}}")], w=8, apilado=True)
    t.serie("Acciones confirmadas por el asesor", [("sum by (accion, resultado) (increase(copiloto_acciones_total[1h]))",
                                                    "{{accion}} · {{resultado}}")], w=12, apilado=True)
    t.serie("Herramientas más usadas", [("topk(6, sum by (tool) (increase(copiloto_tool_llamadas_total[1h])))",
                                         "{{tool}}")], w=12)

    t.fila("Alertas activas (Prometheus → Alertmanager → n8n)")
    t.panel("table", "Alertas disparadas", [('ALERTS{alertstate="firing"}', "")], 24, 6,
            transformations=[{"id": "organize", "options": {"excludeByName": {"Time": True, "Value": True,
                                                                              "__name__": True, "alertstate": True}}}])
    return t


def ml_ingesta() -> Tablero:
    t = Tablero("copiloto-ml-ingesta", "Copiloto · ML, ingesta y RPA",
                "Drift de los modelos (PSI), cascada de intención, frescura de la base de conocimiento y flujos n8n.")
    t.fila("Modelos de ML (ml-service)")
    t.panel("bargauge", "PSI por variable (drift > 0,2)",
            [("max by (modelo, variable) (ml_drift_psi)", "{{modelo}} · {{variable}}")], 12, 9,
            unidad="none", decimales=3, umbrales=[(0.1, "orange"), (0.2, "red")],
            opciones={"orientation": "horizontal", "displayMode": "gradient",
                      "reduceOptions": {"calcs": ["lastNotNull"]}})
    t.stat("SVM dudoso → LLM", "sum(rate(ml_confianza_intencion_bucket{le=\"0.7\"}[1h])) / "
           "clamp_min(sum(rate(ml_confianza_intencion_count[1h])), 1e-9)", w=4, unidad="percentunit", decimales=0,
           descripcion="Fracción de notas con confianza < 0,7 (medido offline: 8 %)")
    t.stat("p95 inferencia", "histogram_quantile(0.95, sum by (le) (rate(ml_latencia_segundos_bucket[1h])))",
           w=4, unidad="s", decimales=3)
    t.panel("table", "Modelos servidos (alias produccion)", [("ml_modelo_cargado", "")], 4, 4,
            transformations=[{"id": "organize", "options": {"excludeByName": {"Time": True, "__name__": True,
                                                                              "instance": True, "job": True}}}])
    t.serie("Inferencias por modelo y resultado", [("sum by (modelo, resultado) (increase(ml_inferencias_total[15m]))",
                                                    "{{modelo}} · {{resultado}}")], w=12, apilado=True)

    t.fila("Ingesta (base de conocimiento)")
    t.stat("Frescura del último documento", "ingesta_frescura_ultima_segundos", w=4, unidad="s", decimales=1,
           umbrales=[(300, "orange"), (900, "red")], descripcion="Meta ≤ 15 min (900 s)")
    t.stat("p95 frescura", "histogram_quantile(0.95, sum by (le) (rate(ingesta_frescura_segundos_bucket[24h])))",
           w=4, unidad="s", decimales=1, umbrales=[(300, "orange"), (900, "red")])
    t.stat("En cola", "ingesta_cola_pendientes", w=4, decimales=0, umbrales=[(5, "orange"), (20, "red")])
    t.stat("Dead-letter", "ingesta_cola_fallidos", w=4, decimales=0, umbrales=[(1, "red")])
    t.serie("Documentos por resultado", [("sum by (resultado) (increase(ingesta_documentos_total[1h]))", "{{resultado}}"),
                                         ("increase(ingesta_errores_total[1h])", "errores")], w=8)

    t.fila("RPA (n8n) y salud")
    t.panel("table", "Servicios monitoreados", [("up", "")], 8, 7,
            transformations=[{"id": "organize", "options": {"excludeByName": {"Time": True, "__name__": True}}}])
    t.stat("Flujos n8n activos", "n8n_active_workflow_count", w=4, decimales=0, umbrales=[(0, "red"), (3, "green")])
    t.serie("Ejecuciones de flujos n8n", [
        ("sum by (status) (increase(n8n_workflow_execution_duration_seconds_count[1h]))", "{{status}}"),
    ], w=12, descripcion="Acción confirmada → ERP, escalamiento → notificación, alertas → acción")
    return t


if __name__ == "__main__":
    DESTINO.mkdir(exist_ok=True)
    for tablero in (agente(), ml_ingesta()):
        (DESTINO / f"{tablero.uid}.json").write_text(
            json.dumps(tablero.json(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        print(f"{tablero.uid}: {len(tablero.paneles)} paneles")
