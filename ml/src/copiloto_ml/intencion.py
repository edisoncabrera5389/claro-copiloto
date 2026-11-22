"""Clasificador de intención: `descripcion` → `categoria`.

Validación honesta: GroupKFold por descripción. Con un split aleatorio la misma nota queda en
entrenamiento y prueba (solo hay 164 notas distintas) y el F1 sale inflado (~0,97): es fuga, no calidad.
"""

from collections.abc import Callable

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, f1_score
from sklearn.model_selection import GroupKFold, StratifiedKFold
from sklearn.naive_bayes import ComplementNB
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

from copiloto_ml.datos import CATEGORIAS


def _tfidf() -> TfidfVectorizer:
    # n-gramas de caracteres 3–5: robustos a errores de tipeo y variaciones ("cancelación"/"cancelacion").
    return TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(3, 5),
        sublinear_tf=True,
        strip_accents="unicode",
        lowercase=True,
        min_df=1,
    )


CANDIDATOS: dict[str, Callable[[], Pipeline]] = {
    "svm_lineal_calibrado": lambda: Pipeline(
        [
            ("tfidf", _tfidf()),
            (
                "clf",
                CalibratedClassifierCV(LinearSVC(C=1.0, class_weight="balanced"), method="sigmoid", cv=3),
            ),
        ]
    ),
    "regresion_logistica": lambda: Pipeline(
        [("tfidf", _tfidf()), ("clf", LogisticRegression(max_iter=3000, class_weight="balanced"))]
    ),
    "naive_bayes_complement": lambda: Pipeline([("tfidf", _tfidf()), ("clf", ComplementNB())]),
    "random_forest": lambda: Pipeline(
        [
            ("tfidf", _tfidf()),
            (
                "clf",
                RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=42, n_jobs=-1),
            ),
        ]
    ),
}
CAMPEON = "svm_lineal_calibrado"


def evaluar(modelo: Callable[[], Pipeline], df: pd.DataFrame, agrupado: bool = True, folds: int = 5) -> dict:
    """F1 macro fuera de muestra. agrupado=True → GroupKFold por descripción (sin fuga)."""
    x, y = df.descripcion.to_numpy(), df.categoria.to_numpy()
    divisor = (
        GroupKFold(n_splits=folds) if agrupado else StratifiedKFold(folds, shuffle=True, random_state=42)
    )
    grupos = df.descripcion.to_numpy() if agrupado else None
    pred = np.empty_like(y)
    f1s = []
    for entreno, prueba in divisor.split(x, y, grupos):
        m = modelo().fit(x[entreno], y[entreno])
        pred[prueba] = m.predict(x[prueba])
        f1s.append(f1_score(y[prueba], pred[prueba], average="macro"))
    return {
        "f1_macro": float(f1_score(y, pred, average="macro")),
        "f1_macro_std": float(np.std(f1s)),
        "matriz_confusion": confusion_matrix(y, pred, labels=CATEGORIAS).tolist(),
    }


def entrenar(df: pd.DataFrame, nombre: str = CAMPEON) -> Pipeline:
    return CANDIDATOS[nombre]().fit(df.descripcion.to_numpy(), df.categoria.to_numpy())
