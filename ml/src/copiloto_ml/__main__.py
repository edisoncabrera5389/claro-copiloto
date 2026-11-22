"""CLI de entrenamiento.

    python -m copiloto_ml entrenar [--modelo intencion|churn|todos] [--sin-mlflow]
    python -m copiloto_ml comparar-llm          # SVM vs LLM zero-shot (requiere LiteLLM)
    python -m copiloto_ml reporte-drift         # informe HTML de Evidently (entrenamiento vs inferencias)

MLFLOW_TRACKING_URI (por defecto http://127.0.0.1:5000) y los CSV en data/raw/03_datos.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from copiloto_ml import churn, drift, intencion
from copiloto_ml.datos import CATEGORICAS_CHURN, NUMERICAS_CHURN, cargar_churn, cargar_tickets

RAIZ = Path(__file__).resolve().parents[3]
DATOS = RAIZ / "data" / "raw" / "03_datos"
GATE_F1_INTENCION = 0.80  # SAD 2.9
GATE_AUC_CHURN = 0.65  # técnico, para uso como señal; la meta de negocio (0,75) no se alcanza y se reporta


def _imprimir(titulo: str, datos: Any) -> None:
    print(f"\n== {titulo} ==\n{json.dumps(datos, ensure_ascii=False, indent=2, default=str)}")


def entrenar_intencion(con_mlflow: bool) -> dict[str, Any]:
    df, rep = cargar_tickets(DATOS / "tickets.csv")
    comparativa = {n: intencion.evaluar(f, df) for n, f in intencion.CANDIDATOS.items()}
    fuga = intencion.evaluar(intencion.CANDIDATOS[intencion.CAMPEON], df, agrupado=False)
    tabla = {n: round(r["f1_macro"], 3) for n, r in comparativa.items()}
    _imprimir("Intención · F1 macro con GroupKFold por descripción", tabla)
    print(f"   (split aleatorio con fuga: F1 {fuga['f1_macro']:.3f} — no se usa para decidir)")
    campeon = comparativa[intencion.CAMPEON]
    modelo = intencion.entrenar(df)
    if not con_mlflow:
        return {"f1_macro": campeon["f1_macro"], "comparativa": tabla}
    from copiloto_ml.registro import registrar

    return registrar(
        "intencion",
        modelo,
        df.descripcion.head(3).to_frame().descripcion.to_numpy().reshape(-1),
        metricas={
            "f1_macro_groupkfold": campeon["f1_macro"],
            "f1_macro_std": campeon["f1_macro_std"],
            "f1_macro_split_aleatorio_con_fuga": fuga["f1_macro"],
            **{f"f1_{n}": v for n, v in tabla.items()},
        },
        parametros={
            "algoritmo": intencion.CAMPEON,
            "features": "tfidf char_wb 3-5",
            "validacion": "GroupKFold(5)",
            "etiquetas": "voto mayoritario por descripción",
            "filas": len(df),
        },
        artefactos={
            "calidad_datos.json": rep.dict(),
            "comparativa.json": tabla,
            "matriz_confusion.json": {
                "etiquetas": intencion.CATEGORIAS,
                "matriz": campeon["matriz_confusion"],
            },
            "referencia_drift.json": {
                "largo_descripcion": drift.referencia_numerica(
                    df.descripcion.str.len().to_numpy(dtype=float)
                ),
                "categoria_predicha": drift.referencia_categorica(df.categoria.tolist()),
            },
        },
        metrica_gate="f1_macro_groupkfold",
        umbral_gate=GATE_F1_INTENCION,
        experimento="intencion",
    )


def entrenar_churn(con_mlflow: bool) -> dict[str, Any]:
    df, rep = cargar_churn(DATOS / "clientes_churn.csv")
    comparativa = {n: churn.evaluar(f, df) for n, f in churn.CANDIDATOS.items()}
    tabla = {
        n: {k: round(v, 3) for k, v in r.items() if k != "probabilidades_oof"} for n, r in comparativa.items()
    }
    _imprimir("Churn · validación StratifiedKFold(5)", tabla)
    campeon = comparativa[churn.CAMPEON]
    umbrales = churn.umbrales(campeon["probabilidades_oof"])
    modelo = churn.entrenar(df)
    if not con_mlflow:
        return {"auc": campeon["auc"], "umbrales": umbrales}
    from copiloto_ml.registro import registrar

    referencia = {c: drift.referencia_numerica(df[c].to_numpy(dtype=float)) for c in NUMERICAS_CHURN}
    referencia |= {
        c: drift.referencia_categorica(df[c].fillna("desconocido").tolist()) for c in CATEGORICAS_CHURN
    }
    return registrar(
        "churn",
        modelo,
        # numéricas como float64: en inferencia llegan faltantes (el CRM no trae NPS, uso de datos ni caídas)
        df[churn.COLUMNAS].head(3).astype({c: "float64" for c in NUMERICAS_CHURN}),
        metricas={
            "auc": campeon["auc"],
            "auc_std": campeon["auc_std"],
            "pr_auc": campeon["pr_auc"],
            "brier": campeon["brier"],
            "tasa_base": campeon["tasa_base"],
            **{f"auc_{n}": r["auc"] for n, r in tabla.items()},
        },
        parametros={
            "algoritmo": churn.CAMPEON,
            "validacion": "StratifiedKFold(5)",
            "meta_negocio_auc": 0.75,
            "uso": "señal de priorización, no decisión",
            "filas": len(df),
        },
        artefactos={
            "calidad_datos.json": rep.dict(),
            "comparativa.json": tabla,
            "umbrales_nivel.json": umbrales,
            "coeficientes.json": churn.coeficientes(modelo),
            "referencia_drift.json": referencia,
        },
        metrica_gate="auc",
        umbral_gate=GATE_AUC_CHURN,
        experimento="churn",
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="copiloto_ml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("entrenar")
    e.add_argument("--modelo", choices=["intencion", "churn", "todos"], default="todos")
    e.add_argument("--sin-mlflow", action="store_true")
    sub.add_parser("comparar-llm")
    sub.add_parser("reporte-drift")
    args = ap.parse_args()
    os.environ.setdefault("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")

    if args.cmd == "entrenar":
        resultados = {}
        if args.modelo in ("intencion", "todos"):
            resultados["intencion"] = entrenar_intencion(not args.sin_mlflow)
        if args.modelo in ("churn", "todos"):
            resultados["churn"] = entrenar_churn(not args.sin_mlflow)
        _imprimir("Resultado", resultados)
        return 0
    if args.cmd == "comparar-llm":
        from copiloto_ml.comparacion_llm import comparar

        df, _ = cargar_tickets(DATOS / "tickets.csv")
        _imprimir("SVM vs LLM zero-shot", comparar(df))
        return 0
    from copiloto_ml.reporte_drift import generar

    print(f"Informe: {generar()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
