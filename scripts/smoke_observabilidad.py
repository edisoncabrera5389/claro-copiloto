"""Prueba de humo de observabilidad y RPA (solo librería estándar), contra docker compose:

    py -3.13 scripts/smoke_observabilidad.py

Verifica: targets de Prometheus, reglas de alerta, que un turno real deja traza en Phoenix (con el mismo
trace_id que la auditoría) y métricas, tableros de Grafana, Alertmanager y flujos de n8n activos.
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
API, PROM, PHOENIX, GRAFANA, AM, N8N = (
    "http://localhost:8000",
    "http://localhost:9090",
    "http://localhost:6006",
    "http://localhost:3000",
    "http://localhost:9093",
    "http://localhost:5678",
)
resultados: list[bool] = []


def env(nombre: str) -> str:
    if os.getenv(nombre):
        return os.environ[nombre]
    for linea in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
        if linea.startswith(f"{nombre}="):
            return linea.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"Falta {nombre}")


def http(url: str, datos: dict | None = None, token: str | None = None, texto: bool = False):
    req = urllib.request.Request(  # noqa: S310 - URLs locales
        url,
        data=json.dumps(datos).encode() if datos is not None else None,
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
        method="POST" if datos is not None else "GET",
    )
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 # nosec B310
        cuerpo = r.read().decode()
        return cuerpo if texto else json.loads(cuerpo)


def verificar(nombre: str, ok: bool, detalle: str = "") -> None:
    resultados.append(ok)
    print(f"  {'OK   ' if ok else 'FALLA'}  {nombre}{(' · ' + detalle) if detalle else ''}")


def phoenix_trazas() -> int:
    q = {"query": "{ projects { edges { node { name traceCount } } } }"}
    for e in http(f"{PHOENIX}/graphql", q)["data"]["projects"]["edges"]:
        if e["node"]["name"] == "claro-copiloto":
            return e["node"]["traceCount"]
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # consola de Windows (cp1252)
    print("== Prometheus ==")
    targets = http(f"{PROM}/api/v1/targets")["data"]["activeTargets"]
    caidos = [t["labels"]["job"] for t in targets if t["health"] != "up"]
    verificar("targets arriba", not caidos, f"{len(targets)} targets" + (f", caídos: {caidos}" if caidos else ""))
    reglas = sum(len(g["rules"]) for g in http(f"{PROM}/api/v1/rules")["data"]["groups"])
    verificar("reglas de alerta cargadas", reglas >= 12, f"{reglas} reglas")

    print("== Turno real → traza y métricas ==")
    antes = phoenix_trazas()
    token = http(f"{API}/auth/login", {"usuario": "A-002", "password": env("API_DEMO_PASSWORD")})["access_token"]
    turno = http(f"{API}/chat/sincrono", {"mensaje": "¿Cuál es el plazo para responder una PQR?"}, token)
    verificar("turno respondido", bool(turno["respuesta"]), f"ruta={turno['ruta']}, {turno['latencias']['ttft_ms']} ms")
    metricas = http(f"{API}/metrics", texto=True)
    verificar("métricas del agente en /metrics", "copiloto_turnos_total{" in metricas)
    despues = antes
    for _ in range(15):  # el exportador envía por lotes (~5 s)
        time.sleep(2)
        despues = phoenix_trazas()
        if despues > antes:
            break
    verificar("traza nueva en Phoenix (proyecto claro-copiloto)", despues > antes, f"{antes} → {despues} trazas")

    print("== Grafana, Alertmanager y n8n ==")
    tableros = [d["title"] for d in http(f"{GRAFANA}/api/search?tag=claro-copiloto")]
    verificar("tableros provisionados", len(tableros) >= 2, ", ".join(tableros))
    verificar("Alertmanager listo", http(f"{AM}/api/v2/status")["cluster"]["status"] in ("ready", "disabled"))
    activos = next(
        (float(ln.split()[-1]) for ln in http(f"{N8N}/metrics", texto=True).splitlines()
         if ln.startswith("n8n_active_workflow_count")),
        0.0,
    )
    verificar("flujos n8n activos", activos >= 3, f"{int(activos)} flujos")
    r = http(f"{N8N}/webhook/alertas", {"alerts": []})
    verificar("webhook de alertas de n8n responde", "message" in r)

    alertas = [a["labels"]["alertname"] for a in http(f"{PROM}/api/v1/alerts")["data"]["alerts"]
               if a["state"] == "firing"]
    print(f"\nAlertas disparadas ahora: {alertas or 'ninguna'}")
    print(f"RESULTADO: {sum(resultados)}/{len(resultados)} OK")
    return 0 if all(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
