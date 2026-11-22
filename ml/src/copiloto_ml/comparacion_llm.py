"""SVM vs LLM con prompt (zero-shot) para la intención: F1, latencia y costo sobre las mismas notas.

Se evalúa sobre las descripciones ÚNICAS (164) con su etiqueta por voto mayoritario: cada nota cuenta una
vez. Es más exigente que el F1 de GroupKFold por ticket (0,92), donde las notas frecuentes pesan más: aquí
mide la generalización a redacciones nuevas (solo hay 6 notas únicas de cancelación y 7 de planes).

También mide la CASCADA que usa la API: SVM si su confianza calibrada ≥ umbral; si no, el LLM.
El LLM se llama vía LiteLLM (alias `economico`).
"""

import json
import os
import statistics
import time
import urllib.request
from typing import Any

import pandas as pd
from sklearn.metrics import f1_score

from copiloto_ml.datos import CATEGORIAS
from copiloto_ml.intencion import CAMPEON, CANDIDATOS

PROMPT = """Clasifica la nota de un asesor de telecomunicaciones en UNA categoría: {categorias}.
Responde solo JSON: {{"categoria": "<categoria>"}}

Nota: {nota}"""
# Precio de referencia de gpt-4.1-mini (USD por millón de tokens): validar con la lista vigente.
PRECIO_ENTRADA, PRECIO_SALIDA = 0.40, 1.60


def _llm(nota: str, url: str, clave: str) -> tuple[str, float, float]:
    cuerpo = {
        "model": "economico",
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": PROMPT.format(categorias=", ".join(CATEGORIAS), nota=nota)}],
    }
    req = urllib.request.Request(  # noqa: S310 - URL local del gateway
        f"{url}/chat/completions",
        data=json.dumps(cuerpo).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {clave}"},
    )
    inicio = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 - URL local del gateway
        datos = json.loads(r.read())
    latencia = time.perf_counter() - inicio
    uso = datos.get("usage", {})
    costo = (
        uso.get("prompt_tokens", 0) * PRECIO_ENTRADA + uso.get("completion_tokens", 0) * PRECIO_SALIDA
    ) / 1e6
    try:
        categoria = json.loads(datos["choices"][0]["message"]["content"]).get("categoria", "")
    except (json.JSONDecodeError, KeyError):
        categoria = ""
    return categoria, latencia, costo


def comparar(
    df: pd.DataFrame, url: str | None = None, clave: str | None = None, umbral: float = 0.7
) -> dict[str, Any]:
    url = url or os.getenv("LLM_URL", "http://127.0.0.1:4000/v1")
    clave = clave or os.getenv("LITELLM_MASTER_KEY", "")
    unicas = df.drop_duplicates("descripcion")[["descripcion", "categoria"]].reset_index(drop=True)

    # SVM: predicción fuera de muestra por grupos (cada nota se predice con un modelo que no la vio)
    from sklearn.model_selection import KFold

    pred_svm, conf_svm, lat_svm = [""] * len(unicas), [0.0] * len(unicas), []
    for entreno, prueba in KFold(5, shuffle=True, random_state=42).split(unicas):
        m = CANDIDATOS[CAMPEON]().fit(
            df[df.descripcion.isin(unicas.descripcion[entreno])].descripcion,
            df[df.descripcion.isin(unicas.descripcion[entreno])].categoria,
        )
        for i in prueba:
            inicio = time.perf_counter()
            prob = m.predict_proba([unicas.descripcion[i]])[0]
            pred_svm[i], conf_svm[i] = m.classes_[prob.argmax()], float(prob.max())
            lat_svm.append(time.perf_counter() - inicio)

    pred_llm, lat_llm, costos = [], [], []
    for nota in unicas.descripcion:
        c, lat, costo = _llm(nota, url, clave)
        pred_llm.append(c)
        lat_llm.append(lat)
        costos.append(costo)

    y = unicas.categoria.tolist()
    seguro = [c >= umbral for c in conf_svm]
    cascada = [s if ok else llm for s, llm, ok in zip(pred_svm, pred_llm, seguro, strict=True)]
    aciertos_seguros = [p == v for p, v, ok in zip(pred_svm, y, seguro, strict=True) if ok]
    return {
        "notas_evaluadas": len(unicas),
        "svm": {
            "f1_macro": round(f1_score(y, pred_svm, average="macro"), 3),
            "latencia_ms_p50": round(statistics.median(lat_svm) * 1000, 2),
            "costo_por_1000_usd": 0.0,
        },
        "llm_zero_shot": {
            "modelo": "gpt-4.1-mini (alias economico)",
            "f1_macro": round(f1_score(y, pred_llm, average="macro", labels=CATEGORIAS), 3),
            "latencia_ms_p50": round(statistics.median(lat_llm) * 1000, 1),
            "costo_por_1000_usd": round(statistics.mean(costos) * 1000, 4),
            "respuestas_invalidas": sum(1 for p in pred_llm if p not in CATEGORIAS),
        },
        "cascada": {
            "regla": f"SVM si confianza >= {umbral}; si no, LLM",
            "f1_macro": round(f1_score(y, cascada, average="macro", labels=CATEGORIAS), 3),
            "fraccion_al_llm": round(1 - sum(seguro) / len(seguro), 3),
            "exactitud_svm_cuando_seguro": round(sum(aciertos_seguros) / max(len(aciertos_seguros), 1), 3),
            "costo_por_1000_usd": round(statistics.mean(costos) * 1000 * (1 - sum(seguro) / len(seguro)), 4),
        },
        "llm_fine_tuning": "No ejecutado: siguiente paso documentado (ver ml/README.md)",
    }
