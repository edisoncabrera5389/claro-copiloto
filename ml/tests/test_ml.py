"""Limpieza, validación sin fuga, PSI y promoción en MLflow (datos sintéticos; corpus real si existe)."""

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from copiloto_ml import churn, drift, intencion
from copiloto_ml.datos import CATEGORIAS, cargar_churn, cargar_tickets

RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "03_datos"
requiere_insumos = pytest.mark.skipif(
    not (RAW / "tickets.csv").is_file(), reason="Faltan los CSV en data/raw"
)

FRASES = {
    "soporte_tecnico": [
        "internet lento en las noches",
        "el módem no enciende",
        "sin señal de fibra",
        "la wifi se cae",
    ],
    "facturacion": [
        "cobro doble en la factura",
        "no reconozco un cargo",
        "la factura llegó alta",
        "pagué y sale deuda",
    ],
    "consulta_planes": [
        "quiere conocer planes de fibra",
        "pregunta precio del plan",
        "desea mejorar su plan",
        "info de planes",
    ],
    "cancelacion": [
        "solicita cancelar el servicio",
        "quiere dar de baja",
        "desea retirar la línea",
        "pide la cancelación",
    ],
    "portabilidad": [
        "quiere portar su número",
        "solicita portabilidad",
        "se cambia de operador con su número",
        "pide el NIP",
    ],
}


def tickets_sinteticos(ruta: Path) -> Path:
    filas, n = [], 0
    for cat, frases in FRASES.items():
        for f in frases:
            for rep in range(6):
                n += 1
                filas.append(
                    {
                        "ticket_id": f"TK-{n}",
                        "cliente_id": "CL-1",
                        "categoria": cat if rep else "facturacion",
                        "descripcion": f,
                    }
                )
    filas.append(dict(filas[0]))  # duplicado exacto
    pd.DataFrame(filas).to_csv(ruta, index=False, encoding="utf-8-sig")
    return ruta


def churn_sintetico(ruta: Path, n: int = 400) -> Path:
    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "cliente_id": [f"CL-{i}" for i in range(n)],
            "valor_mensual": rng.integers(40_000, 250_000, n).astype(float),
            "antiguedad_meses": rng.integers(0, 120, n).astype(float),
            "dias_mora": rng.integers(0, 90, n),
            "tickets_90d": rng.integers(0, 5, n),
            "tickets_tecnicos_90d": rng.integers(0, 3, n),
            "caidas_servicio_90d": rng.integers(0, 5, n),
            "uso_datos_gb_mes": rng.uniform(1, 100, n),
            "nps_ultimo": rng.integers(0, 11, n).astype(float),
            "ofertas_retencion_12m": rng.integers(0, 2, n),
            "tipo_servicio": rng.choice(["hogar", "movil", "convergente"], n),
            "metodo_pago": rng.choice(["pse", "efectivo", None], n),
            "ciudad": rng.choice(["Cali", None], n),
        }
    )
    df["churn_90d"] = ((df.dias_mora > 45) | (df.tickets_90d >= 3)).astype(int)
    df.loc[0, "antiguedad_meses"], df.loc[1, "valor_mensual"], df.loc[2, "uso_datos_gb_mes"] = -5, 0, 8786
    pd.concat([df, df.iloc[[3]]]).to_csv(ruta, index=False, encoding="utf-8-sig")
    return ruta


def test_tickets_duplicados_y_voto_mayoritario(tmp_path):
    df, rep = cargar_tickets(tickets_sinteticos(tmp_path / "t.csv"))
    assert rep.duplicados == 1 and rep.correcciones["descripciones_unicas"] == 20
    # 1 de cada 6 etiquetas es "facturacion": hay ruido en 16 notas (en las 4 de facturación coincide)
    assert rep.correcciones["descripciones_con_ruido"] == 16
    assert (df.groupby("descripcion").categoria.nunique() == 1).all()
    assert df[df.descripcion == "sin señal de fibra"].categoria.unique().tolist() == ["soporte_tecnico"]


def test_churn_limpieza_de_atipicos(tmp_path):
    df, rep = cargar_churn(churn_sintetico(tmp_path / "c.csv"))
    assert rep.duplicados == 1 and len(df) == 400
    assert rep.correcciones["antiguedad_negativa"] == 1 and rep.correcciones["valor_mensual_no_positivo"] == 1
    assert rep.correcciones["uso_datos_imposible"] == 1 and math.isnan(df.loc[2, "uso_datos_gb_mes"])


def test_groupkfold_no_tiene_fuga_y_el_split_aleatorio_si(tmp_path):
    df, _ = cargar_tickets(tickets_sinteticos(tmp_path / "t.csv"))
    honesto = intencion.evaluar(intencion.CANDIDATOS["regresion_logistica"], df, folds=4)
    con_fuga = intencion.evaluar(intencion.CANDIDATOS["regresion_logistica"], df, agrupado=False, folds=4)
    assert con_fuga["f1_macro"] == 1.0  # la misma nota en entrenamiento y prueba
    assert honesto["f1_macro"] < con_fuga["f1_macro"]
    assert np.array(honesto["matriz_confusion"]).shape == (5, 5)


def test_modelo_de_intencion_entrena_y_da_probabilidades(tmp_path):
    df, _ = cargar_tickets(tickets_sinteticos(tmp_path / "t.csv"))
    m = intencion.entrenar(df)
    prob = m.predict_proba(["quiero cancelar el internet"])[0]
    assert list(m.classes_) == sorted(CATEGORIAS) and abs(sum(prob) - 1) < 1e-6


def test_churn_evalua_umbrales_y_coeficientes(tmp_path):
    df, _ = cargar_churn(churn_sintetico(tmp_path / "c.csv"))
    r = churn.evaluar(churn.CANDIDATOS["regresion_logistica"], df, folds=3)
    assert r["auc"] > 0.8 and 0 < r["tasa_base"] < 1
    u = churn.umbrales(r["probabilidades_oof"])
    assert u["alto"] > u["medio"]
    m = churn.entrenar(df)
    coef = churn.coeficientes(m)
    assert list(coef)[0].startswith("num__")  # la variable más influyente es numérica (mora o tickets)
    assert churn.coeficientes(churn.entrenar(df, "random_forest")) == {}
    # El pipeline tolera las variables que el CRM no trae (se imputan)
    fila = df[churn.COLUMNAS].head(1).copy()
    fila[["nps_ultimo", "uso_datos_gb_mes", "caidas_servicio_90d", "metodo_pago"]] = None
    assert 0 <= m.predict_proba(fila)[0, 1] <= 1


def test_psi_numerica_y_categorica():
    rng = np.random.default_rng(1)
    ref = drift.referencia_numerica(rng.normal(0, 1, 2000))
    assert drift.psi(ref, rng.normal(0, 1, 500).tolist()) < 0.1
    assert drift.psi(ref, rng.normal(2, 1, 500).tolist()) > drift.UMBRAL_ALERTA
    assert drift.psi(ref, [1.0] * 5) is None and drift.psi(ref, [None] * 20) is None
    cat = drift.referencia_categorica(["a"] * 50 + ["b"] * 50)
    assert drift.psi(cat, ["a"] * 25 + ["b"] * 25) < 0.01
    assert drift.psi(cat, ["c"] * 30) > drift.UMBRAL_ALERTA and drift.psi(cat, ["a"]) is None


def test_registro_promueve_solo_si_pasa_gate_y_supera_al_campeon(tmp_path, monkeypatch):
    import mlflow

    from copiloto_ml.registro import registrar

    mlflow.set_tracking_uri(f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}")
    df, _ = cargar_tickets(tickets_sinteticos(tmp_path / "t.csv"))
    modelo = intencion.entrenar(df, "regresion_logistica")
    x = df.descripcion.head(2).to_numpy()

    def correr(f1):
        return registrar(
            "intencion_prueba",
            modelo,
            x,
            {"f1": f1},
            {"algoritmo": "lr"},
            {"a.json": {"x": 1}},
            "f1",
            0.80,
            f"exp-{tmp_path.name}",
        )

    assert correr(0.85)["promovido_a_produccion"]  # primera versión que pasa el gate
    r = correr(0.83)
    assert not r["promovido_a_produccion"] and r["campeon_anterior"] == 0.85  # no supera al campeón
    assert not correr(0.70)["pasa_gate"]
    r = correr(0.90)
    assert r["promovido_a_produccion"] and str(r["version"]) == "4"
    cargado = mlflow.sklearn.load_model("models:/intencion_prueba@produccion")
    assert cargado.predict(["quiero portar mi número"])[0] in CATEGORIAS


@requiere_insumos
def test_corpus_real_reproduce_los_hallazgos():
    t, rep = cargar_tickets(RAW / "tickets.csv")
    assert rep.duplicados == 20 and rep.correcciones["descripciones_unicas"] == 164
    assert intencion.evaluar(intencion.CANDIDATOS[intencion.CAMPEON], t)["f1_macro"] >= 0.80  # gate del SAD
    c, rep_c = cargar_churn(RAW / "clientes_churn.csv")
    assert rep_c.duplicados == 12 and rep_c.correcciones["antiguedad_negativa"] == 15
    assert 0.65 <= churn.evaluar(churn.CANDIDATOS[churn.CAMPEON], c)["auc"] < 0.75  # bajo la meta: se reporta
