"""Informe de drift con Evidently: datos de entrenamiento (referencia) vs inferencias reales del ml-service.

    python -m copiloto_ml reporte-drift      # → ml/reportes/drift_churn_<fecha>.html

Las inferencias se leen de GET /drift/muestras del ml-service (las guarda al predecir). El cálculo diario
de PSI lo hace el propio servicio (GET /drift); este informe es el análisis visual para el equipo de datos.
"""

import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

from copiloto_ml.datos import CATEGORICAS_CHURN, NUMERICAS_CHURN, cargar_churn

RAIZ = Path(__file__).resolve().parents[3]


def muestras_servicio(url: str) -> pd.DataFrame:
    with urllib.request.urlopen(f"{url}/drift/muestras?modelo=churn", timeout=30) as r:  # noqa: S310 - URL local
        return pd.DataFrame(json.loads(r.read()))


def generar(actual: pd.DataFrame | None = None, destino: Path | None = None) -> Path:
    from evidently import DataDefinition, Dataset, Report
    from evidently.presets import DataDriftPreset

    referencia, _ = cargar_churn(RAIZ / "data" / "raw" / "03_datos" / "clientes_churn.csv")
    if actual is None:
        actual = muestras_servicio(os.getenv("ML_SERVICE_URL", "http://127.0.0.1:8001"))
    if len(actual) < 5:
        raise SystemExit("Muy pocas inferencias registradas para comparar (mínimo 5)")
    act = actual.reindex(columns=NUMERICAS_CHURN + CATEGORICAS_CHURN).copy()
    # Variables que el CRM de la demo no entrega (NPS, uso de datos, caídas, método de pago): llegan vacías y
    # el modelo las imputa; no hay distribución actual que comparar → se excluyen y se informan.
    vacias = [c for c in act.columns if act[c].isna().all()]
    if vacias:
        print(f"Sin datos en producción (excluidas del informe): {', '.join(vacias)}")
    numericas = [c for c in NUMERICAS_CHURN if c not in vacias]
    categoricas = [c for c in CATEGORICAS_CHURN if c not in vacias]
    definicion = DataDefinition(numerical_columns=numericas, categorical_columns=categoricas)
    ref = referencia[numericas + categoricas].copy()
    act = act[numericas + categoricas]
    for df in (ref, act):
        df[categoricas] = df[categoricas].fillna("desconocido")
        df[numericas] = df[numericas].apply(pd.to_numeric, errors="coerce")
    snap = Report([DataDriftPreset()]).run(
        current_data=Dataset.from_pandas(act, data_definition=definicion),
        reference_data=Dataset.from_pandas(ref, data_definition=definicion),
    )
    destino = destino or RAIZ / "ml" / "reportes" / f"drift_churn_{datetime.now():%Y%m%d_%H%M}.html"
    destino.parent.mkdir(parents=True, exist_ok=True)
    snap.save_html(str(destino))
    return destino
