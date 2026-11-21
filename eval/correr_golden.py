"""Evaluación automática con el golden dataset (30 preguntas) contra la API en ejecución.

    py -3.13 eval/correr_golden.py                     # completa, con LLM juez (groundedness)
    py -3.13 eval/correr_golden.py --sin-juez          # sin juez (más rápido y barato)
    py -3.13 eval/correr_golden.py --ids GQ-18 GQ-26   # subconjunto

Solo librería estándar. Usa /chat (SSE) para medir el TTFT real. Cada pregunta va en una sesión nueva
(sin memoria compartida). Métricas y umbrales del caso:

| KPI                    | Cálculo                                                                 | Meta    |
|------------------------|-------------------------------------------------------------------------|---------|
| Exactitud golden       | % con TODOS sus puntos clave (literal o, con juez, la idea)             | ≥ 80 %  |
| Exactitud literal      | lo mismo pero solo coincidencia de texto (informativa, más estricta)    | —       |
| Groundedness           | LLM juez (tier alto): afirmaciones respaldadas por el contexto citado, | ≥ 0,85  |
|                        | en respuestas documentales (sin datos de CRM, que el juez no ve)        |         |
| Recall@k               | promedio de fuentes del golden presentes entre las recuperadas          | ≥ 0,90  |
| Sin cita               | % de respuestas de conocimiento sin ninguna cita [n]                    | ≤ 5 %   |
| Éxito de tareas        | % de preguntas con tools en que se usaron las esperadas                 | ≥ 90 %  |
| Acciones no permitidas | escrituras ejecutadas sin confirmación (deben ser solo propuestas)      | 0       |
| p95 TTFT / total       | latencia hasta el primer token y total                         | ≤ 2 s / ≤ 8 s |

Salida: eval/reportes/golden_<fecha>.json y .md (no versionados: contienen las preguntas del insumo).
Código de salida 1 si algún KPI con meta no se cumple.
"""

import argparse
import json
import os
import re
import statistics
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
# Tools equivalentes: evaluarRetencion y listarServicios consultan la ficha del cliente en el CRM.
EQUIVALENCIAS = {
    "obtenerCliente": {"obtenerCliente", "listarServicios", "evaluarRetencion", "buscarCliente"},
    "listarTickets": {"listarTickets", "evaluarRetencion"},
}
ESCRITURA = {"crearTicket", "registrarOfertaRetencion", "aplicarAjuste"}
JUEZ = """Eres un evaluador estricto de un asistente RAG. Responde SOLO JSON con dos evaluaciones:
1. "groundedness": fracción (0 a 1) de las afirmaciones factuales de la RESPUESTA respaldadas por el CONTEXTO
   (fragmentos de fuentes oficiales). Ignora cortesías y recomendaciones genéricas que no afirmen hechos.
   Si no hay CONTEXTO, usa null.
2. "puntos": para cada PUNTO CLAVE, true si la RESPUESTA expresa esa idea (aunque use otras palabras),
   si no false.
{{"groundedness": <0 a 1 o null>, "no_respaldadas": ["afirmación", ...], "puntos": {{"<punto>": true|false}}}}

PREGUNTA: {pregunta}
PUNTOS CLAVE: {puntos}

CONTEXTO:
{contexto}

RESPUESTA:
{respuesta}"""


def env(nombre: str) -> str:
    if os.getenv(nombre):
        return os.environ[nombre]
    for linea in (RAIZ / ".env").read_text(encoding="utf-8").splitlines():
        if linea.strip().startswith(f"{nombre}="):
            return linea.split("=", 1)[1].strip().strip("'\"")
    return ""


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    texto = re.sub(r"(\d)\s+%", r"\1%", texto)  # "30 %" == "30%"
    return re.sub(r"\s+", " ", texto)


def doc_id(fuente: str) -> str:
    base = re.sub(r"\.(pdf|docx|md|eml|txt|wav)$", "", fuente.lower())
    return re.sub(r"[_\-\s]v\d+(\.\d+)?$", "", base)


def http(metodo: str, url: str, cuerpo: Any = None, token: str = "", timeout: int = 120) -> Any:
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(
        url,
        data=datos,
        method=metodo,
        headers={  # noqa: S310 - URL local
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
        return json.loads(r.read())


def chat_sse(api: str, token: str, mensaje: str) -> tuple[dict[str, Any], float | None]:
    """Devuelve (evento fin, ttft medido por el cliente)."""
    req = urllib.request.Request(
        f"{api}/chat",
        data=json.dumps({"mensaje": mensaje}).encode(),
        method="POST",  # noqa: S310
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "Accept": "text/event-stream",
        },
    )
    inicio, ttft, evento, fin = time.perf_counter(), None, None, None
    for intento in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:  # noqa: S310
                for crudo in r:
                    linea = crudo.decode("utf-8").rstrip("\r\n")
                    if linea.startswith("event:"):
                        evento = linea[6:].strip()
                    elif linea.startswith("data:") and evento:
                        if evento == "token" and ttft is None:
                            ttft = time.perf_counter() - inicio
                        if evento == "fin":
                            fin = json.loads(linea[5:].strip())
                        if evento == "error":
                            raise RuntimeError(linea[5:].strip())
            break
        except urllib.error.HTTPError as e:
            if e.code != 429 or intento == 2:
                raise
            time.sleep(int(e.headers.get("Retry-After", "60")))
            inicio = time.perf_counter()
    if fin is None:
        raise RuntimeError("el stream terminó sin evento fin")
    return fin, ttft


def juzgar(q: dict[str, Any], fin: dict[str, Any]) -> dict[str, Any]:
    citadas = [f for f in fin["fuentes"] if f.get("citada")] or fin["fuentes"]
    contexto = (
        "\n\n".join(
            f"[{f['n']}] {f['fuente']} · {f.get('seccion') or ''}\n{f.get('extracto', '')}" for f in citadas
        )
        or "(sin contexto documental: respuesta basada en sistemas o reglas)"
    )
    cuerpo = {
        "model": "alto",
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "user",
                "content": JUEZ.format(
                    pregunta=q["pregunta"],
                    puntos=json.dumps(q["puntos_clave"], ensure_ascii=False),
                    contexto=contexto,
                    respuesta=fin["respuesta"],
                ),
            }
        ],
    }
    r = http("POST", "http://127.0.0.1:4000/v1/chat/completions", cuerpo, env("LITELLM_MASTER_KEY"))
    juicio = json.loads(r["choices"][0]["message"]["content"])
    # Groundedness solo para respuestas documentales: si se usaron tools de CRM/Facturación, parte de la
    # respuesta viene de esos datos, que el juez no ve (se evalúan con el éxito de tareas y los puntos clave).
    usa_sistemas = any(t["ok"] and t["nombre"] != "buscar_conocimiento" for t in fin["tools"])
    if not citadas or usa_sistemas:
        juicio["groundedness"] = None
    return juicio


def p95(valores: list[float]) -> float:
    v = sorted(valores)
    return v[min(len(v) - 1, round(0.95 * (len(v) - 1)))] if v else 0.0


def evaluar(
    q: dict[str, Any], fin: dict[str, Any], ttft: float | None, juicio: dict[str, Any] | None
) -> dict[str, Any]:
    resp = normalizar(fin["respuesta"])
    literales = {c: normalizar(c) in resp for c in q["puntos_clave"]}
    semanticos = (juicio or {}).get("puntos") or {}
    claves = {c: literales[c] or bool(semanticos.get(c)) for c in q["puntos_clave"]}
    usadas = {t["nombre"] for t in fin["tools"] if t["ok"]} | {p["accion"] for p in fin["propuestas"]}
    grupos = {
        g: any(t in usadas for alt in g.split("|") for t in EQUIVALENCIAS.get(alt, {alt}))
        for g in q["herramientas_esperadas"]
    }
    golden_docs = {doc_id(f) for f in q["fuentes"] if not f.endswith("-api")}
    recuperados = {doc_id(f["fuente"]) for f in fin["fuentes"]}
    ejecutadas = [
        t["nombre"]
        for t in fin["tools"]
        if t["nombre"] in ESCRITURA
        and t["ok"]
        and not t.get("automatica")
        and not any(p["accion"] == t["nombre"] for p in fin["propuestas"])
    ]
    return {
        "id": q["id"],
        "categoria": q["categoria"],
        "ruta": fin["ruta"],
        "intencion": fin["intencion"],
        "aprobada": all(claves.values()),
        "aprobada_literal": all(literales.values()),
        "cobertura_claves": sum(claves.values()) / max(1, len(claves)),
        "claves_faltantes": [c for c, ok in claves.items() if not ok],
        "claves_solo_semanticas": [c for c in claves if claves[c] and not literales[c]],
        "tools_ok": all(grupos.values()) if grupos else None,
        "tools_usadas": sorted(usadas),
        "recall": len(golden_docs & recuperados) / len(golden_docs) if golden_docs else None,
        "sin_cita": bool(golden_docs) and not any(f.get("citada") for f in fin["fuentes"]),
        "groundedness": juicio.get("groundedness") if juicio else None,
        "no_respaldadas": juicio.get("no_respaldadas", []) if juicio else [],
        "acciones_no_permitidas": ejecutadas,
        "confianza": fin["confianza"],
        "ttft_s": round(ttft, 3) if ttft is not None else None,
        "total_s": fin["latencias"]["total_ms"] / 1000,
        "costo_usd": fin["uso"]["costo_usd"],
        "modelo": fin["modelo"],
        "respuesta": fin["respuesta"],
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    ap.add_argument("--golden", type=Path, default=RAIZ / "data/raw/05_evaluacion/golden_dataset.jsonl")
    ap.add_argument("--usuario", default="A-001")
    ap.add_argument("--sin-juez", action="store_true")
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--etiqueta", default="", help="Texto para el nombre del reporte (ej. con-reranker)")
    args = ap.parse_args()

    lineas = args.golden.read_text(encoding="utf-8").splitlines()
    preguntas = [json.loads(linea) for linea in lineas if linea.strip()]
    if args.ids:
        preguntas = [q for q in preguntas if q["id"] in args.ids]
    token = http(
        "POST", f"{args.api}/auth/login", {"usuario": args.usuario, "password": env("API_DEMO_PASSWORD")}
    )["access_token"]
    salud = http("GET", f"{args.api}/health")
    resultados = []
    for q in preguntas:
        try:
            fin, ttft = chat_sse(args.api, token, q["pregunta"])
            juicio = None if args.sin_juez else juzgar(q, fin)
            r = evaluar(q, fin, ttft, juicio)
        except Exception as e:  # una pregunta que falla cuenta como no aprobada
            r = {
                "id": q["id"],
                "categoria": q["categoria"],
                "aprobada": False,
                "error": f"{type(e).__name__}: {e}"[:300],
            }
        resultados.append(r)
        marca = "✅" if r.get("aprobada") else "❌"
        print(
            f"{marca} {r['id']} {r.get('ruta', '-'):12} claves={r.get('cobertura_claves', 0):.0%} "
            f"tools={r.get('tools_ok')} recall={r.get('recall')} ground={r.get('groundedness')} "
            f"ttft={r.get('ttft_s')}s total={r.get('total_s')}s "
            f"{r.get('claves_faltantes') or r.get('error') or ''}"
        )

    ok = [r for r in resultados if "error" not in r]
    con_fuentes = [r for r in ok if r.get("recall") is not None]
    con_tools = [r for r in ok if r.get("tools_ok") is not None]
    ground = [r["groundedness"] for r in ok if r.get("groundedness") is not None]
    kpis = {
        "exactitud_golden": sum(r["aprobada"] for r in resultados) / len(resultados),
        "exactitud_literal": sum(r.get("aprobada_literal", False) for r in resultados) / len(resultados),
        "cobertura_puntos_clave": statistics.mean(r.get("cobertura_claves", 0) for r in resultados),
        "groundedness": statistics.mean(ground) if ground else None,
        "recall_k": statistics.mean(r["recall"] for r in con_fuentes) if con_fuentes else None,
        "sin_cita": sum(r["sin_cita"] for r in con_fuentes) / len(con_fuentes) if con_fuentes else None,
        "exito_tareas": sum(r["tools_ok"] for r in con_tools) / len(con_tools) if con_tools else None,
        "acciones_no_permitidas": sum(len(r["acciones_no_permitidas"]) for r in ok),
        "p50_ttft_s": statistics.median(r["ttft_s"] for r in ok if r["ttft_s"]) if ok else None,
        "p95_ttft_s": p95([r["ttft_s"] for r in ok if r["ttft_s"]]),
        "p95_total_s": p95([r["total_s"] for r in ok]),
        "costo_total_usd": round(sum(r["costo_usd"] for r in ok), 4),
        "costo_promedio_usd": round(statistics.mean(r["costo_usd"] for r in ok), 5) if ok else None,
        "errores": len(resultados) - len(ok),
    }
    metas = {
        "exactitud_golden": (">=", 0.80),
        "groundedness": (">=", 0.85),
        "recall_k": (">=", 0.90),
        "sin_cita": ("<=", 0.05),
        "exito_tareas": (">=", 0.90),
        "acciones_no_permitidas": ("<=", 0),
        "p95_ttft_s": ("<=", 2.0),
        "p95_total_s": ("<=", 8.0),
    }
    cumple = {
        k: (kpis[k] is not None and (kpis[k] >= v if op == ">=" else kpis[k] <= v))
        for k, (op, v) in metas.items()
        if kpis[k] is not None
    }

    fecha = datetime.now().strftime("%Y%m%d_%H%M")
    destino = RAIZ / "eval" / "reportes"
    destino.mkdir(parents=True, exist_ok=True)
    nombre = f"golden_{fecha}{'_' + args.etiqueta if args.etiqueta else ''}"
    (destino / f"{nombre}.json").write_text(
        json.dumps(
            {
                "fecha": fecha,
                "etiqueta": args.etiqueta,
                "salud_api": salud,
                "kpis": kpis,
                "cumple": cumple,
                "resultados": resultados,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    filas = [
        f"| {k} | {kpis[k]:.3f} | {metas[k][0]} {metas[k][1]} | {'✅' if cumple.get(k) else '❌'} |"
        if isinstance(kpis[k], float)
        else f"| {k} | {kpis[k]} | {metas[k][0]} {metas[k][1]} | {'✅' if cumple.get(k) else '❌'} |"
        for k in metas
        if kpis[k] is not None
    ]
    md = [
        f"# Evaluación golden · {fecha} {args.etiqueta}",
        "",
        f"Reranker: {salud['componentes'].get('reranker')} · prompts: {salud.get('prompts')}",
        "",
        "| KPI | Valor | Meta | |",
        "|---|---|---|---|",
        *filas,
        "",
        f"Costo total: US$ {kpis['costo_total_usd']} · "
        f"promedio por pregunta: US$ {kpis['costo_promedio_usd']} · "
        f"p50 TTFT: {kpis['p50_ttft_s']} s · errores: {kpis['errores']}",
        "",
        "| ID | Aprobada | Faltantes |",
        "|---|---|---|",
        *[
            f"| {r['id']} | {'✅' if r.get('aprobada') else '❌'} | "
            f"{', '.join(r.get('claves_faltantes', [])) or r.get('error', '')} |"
            for r in resultados
        ],
    ]
    (destino / f"{nombre}.md").write_text("\n".join(md), encoding="utf-8")
    print("\n" + "\n".join(md[: len(filas) + 8]))
    print(f"\nReporte: eval/reportes/{nombre}.md")
    return 0 if all(cumple.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
