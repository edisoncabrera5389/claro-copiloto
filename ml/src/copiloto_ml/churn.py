"""Riesgo de cancelación a 90 días: variables de clientes_churn.csv → churn_90d.

Se usa como SEÑAL de priorización (orden de atención, Mesa Especializada), nunca como decisión: la
elegibilidad la decide la política de retención en código. Probado y descartado: agregados de tickets por
cliente (AUC 0,708 con y sin ellos; la señal ya está en tickets_90d).
"""

from collections.abc import Callable

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from copiloto_ml.datos import CATEGORICAS_CHURN, NUMERICAS_CHURN

COLUMNAS = NUMERICAS_CHURN + CATEGORICAS_CHURN


def _preprocesador(escalar: bool = True) -> ColumnTransformer:
    numericas = [SimpleImputer(strategy="median", add_indicator=True)] + (
        [StandardScaler()] if escalar else []
    )
    return ColumnTransformer(
        [
            ("num", make_pipeline(*numericas), NUMERICAS_CHURN),
            # "desconocido": el CRM de la demo no trae método de pago (se imputa, no se inventa)
            (
                "cat",
                make_pipeline(
                    SimpleImputer(strategy="constant", fill_value="desconocido"),
                    OneHotEncoder(handle_unknown="ignore"),
                ),
                CATEGORICAS_CHURN,
            ),
        ]
    )


CANDIDATOS: dict[str, Callable[[], Pipeline]] = {
    "regresion_logistica": lambda: Pipeline(
        [
            ("pre", _preprocesador()),
            ("clf", LogisticRegression(max_iter=3000, class_weight="balanced", C=0.5)),
        ]
    ),
    "hist_gradient_boosting": lambda: Pipeline(
        [
            ("pre", _preprocesador(escalar=False)),
            (
                "clf",
                HistGradientBoostingClassifier(
                    max_depth=3, learning_rate=0.05, max_iter=300, class_weight="balanced", random_state=42
                ),
            ),
        ]
    ),
    "random_forest": lambda: Pipeline(
        [
            ("pre", _preprocesador(escalar=False)),
            (
                "clf",
                RandomForestClassifier(
                    n_estimators=400, min_samples_leaf=10, class_weight="balanced", random_state=42, n_jobs=-1
                ),
            ),
        ]
    ),
}
CAMPEON = "regresion_logistica"  # interpretable por sus coeficientes; los retadores no la superan


def evaluar(modelo: Callable[[], Pipeline], df: pd.DataFrame, folds: int = 5) -> dict:
    x, y = df[COLUMNAS], df.churn_90d.to_numpy()
    prob = np.zeros(len(y))
    aucs = []
    for entreno, prueba in StratifiedKFold(folds, shuffle=True, random_state=42).split(x, y):
        m = modelo().fit(x.iloc[entreno], y[entreno])
        prob[prueba] = m.predict_proba(x.iloc[prueba])[:, 1]
        aucs.append(roc_auc_score(y[prueba], prob[prueba]))
    return {
        "auc": float(roc_auc_score(y, prob)),
        "auc_std": float(np.std(aucs)),
        "pr_auc": float(average_precision_score(y, prob)),
        "brier": float(brier_score_loss(y, prob)),
        "tasa_base": float(y.mean()),
        "probabilidades_oof": prob,
    }


def umbrales(prob: np.ndarray) -> dict[str, float]:
    """Niveles por percentil de la población: alto = 20 % más riesgoso, medio = siguiente 30 %."""
    return {"alto": float(np.quantile(prob, 0.80)), "medio": float(np.quantile(prob, 0.50))}


def entrenar(df: pd.DataFrame, nombre: str = CAMPEON) -> Pipeline:
    return CANDIDATOS[nombre]().fit(df[COLUMNAS], df.churn_90d.to_numpy())


def coeficientes(modelo: Pipeline) -> dict[str, float]:
    """Interpretabilidad: peso de cada variable (solo regresión logística)."""
    clf = modelo.named_steps["clf"]
    if not hasattr(clf, "coef_"):
        return {}
    nombres = modelo.named_steps["pre"].get_feature_names_out()
    return {
        n: round(float(c), 4)
        for n, c in sorted(zip(nombres, clf.coef_[0], strict=True), key=lambda p: -abs(p[1]))
    }
