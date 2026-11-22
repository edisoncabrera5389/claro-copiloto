"""Drift con PSI (Population Stability Index). Referencia = distribución de entrenamiento por variable.

PSI = Σ (actual − esperado) · ln(actual / esperado) por bin. < 0,1 estable · 0,1–0,2 moderado · > 0,2
cambio significativo → alerta y reentrenamiento (SAD 2.14). Mismo cálculo en el ml-service (copia
verificada con una prueba de contrato).
"""

import math
from typing import Any

import numpy as np

UMBRAL_ALERTA = 0.2
EPS = 1e-4


def referencia_numerica(valores: np.ndarray, bins: int = 10) -> dict[str, Any]:
    v = valores[~np.isnan(valores)]
    cortes = np.unique(np.quantile(v, np.linspace(0, 1, bins + 1)))
    conteos = np.histogram(v, bins=cortes)[0]
    return {
        "tipo": "numerica",
        "cortes": cortes.tolist(),
        "proporciones": (conteos / conteos.sum()).tolist(),
        "faltantes": float(np.isnan(valores).mean()),
    }


def referencia_categorica(valores: list[Any]) -> dict[str, Any]:
    total = len(valores)
    conteo: dict[str, int] = {}
    for x in valores:
        conteo[str(x)] = conteo.get(str(x), 0) + 1
    return {"tipo": "categorica", "proporciones": {k: n / total for k, n in conteo.items()}}


def psi(referencia: dict[str, Any], valores: list[Any]) -> float | None:
    """PSI de una muestra contra la referencia. None si no hay datos suficientes."""
    if referencia["tipo"] == "numerica":
        arr = np.array([np.nan if v is None else float(v) for v in valores], dtype=float)
        arr = arr[~np.isnan(arr)]
        if len(arr) < 10:
            return None
        cortes = np.array(referencia["cortes"], dtype=float)
        actual = np.histogram(np.clip(arr, cortes[0], cortes[-1]), bins=cortes)[0] / len(arr)
        esperado = np.array(referencia["proporciones"], dtype=float)
        pares = zip(esperado.tolist(), actual.tolist(), strict=True)
    else:
        if len(valores) < 10:
            return None
        esperado_d = referencia["proporciones"]
        claves = set(esperado_d) | {str(v) for v in valores}
        actual_d = {k: sum(1 for v in valores if str(v) == k) / len(valores) for k in claves}
        pares = ((esperado_d.get(k, 0.0), actual_d[k]) for k in claves)
    return float(sum((a - e) * math.log(max(a, EPS) / max(e, EPS)) for e, a in pares))
