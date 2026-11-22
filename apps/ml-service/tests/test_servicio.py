"""Servicio de modelos con modelos reales pequeños (entrenados en la prueba) y un cargador falso."""

import importlib.util
from pathlib import Path

import mongomock
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from copiloto_ml_service import caracteristicas, drift
from copiloto_ml_service.app import crear_app
from copiloto_ml_service.config import Settings
from copiloto_ml_service.modelos import ModeloCargado

HOY = "2026-11-18"


def modelo_intencion():
    textos = [
        "quiero cancelar el servicio",
        "dar de baja la línea",
        "cobro doble en la factura",
        "factura alta",
        "internet lento",
        "el módem no enciende",
    ] * 3
    etiquetas = [
        "cancelacion",
        "cancelacion",
        "facturacion",
        "facturacion",
        "soporte_tecnico",
        "soporte_tecnico",
    ] * 3
    return Pipeline(
        [
            ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))),
            ("clf", LogisticRegression(max_iter=1000)),
        ]
    ).fit(textos, etiquetas)


def modelo_churn():
    rng = np.random.default_rng(0)
    n = 300
    df = pd.DataFrame({c: rng.integers(0, 10, n).astype(float) for c in caracteristicas.NUMERICAS})
    df["dias_mora"] = rng.integers(0, 90, n).astype(float)
    df["tipo_servicio"] = rng.choice(["hogar", "movil", "convergente"], n)
    df["metodo_pago"] = rng.choice(["pse", "efectivo"], n)
    y = (df.dias_mora > 45).astype(int)
    pre = ColumnTransformer(
        [
            (
                "num",
                make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler()),
                caracteristicas.NUMERICAS,
            ),
            (
                "cat",
                make_pipeline(
                    SimpleImputer(strategy="constant", fill_value="desconocido"),
                    OneHotEncoder(handle_unknown="ignore"),
                ),
                caracteristicas.CATEGORICAS,
            ),
        ]
    )
    modelo = Pipeline([("pre", pre), ("clf", LogisticRegression(max_iter=1000))]).fit(df, y)
    referencia = {c: drift.referencia_numerica(df[c].to_numpy()) for c in caracteristicas.NUMERICAS}
    referencia |= {c: drift.referencia_categorica(df[c].tolist()) for c in caracteristicas.CATEGORICAS}
    return modelo, referencia


class CargadorFalso:
    def __init__(self, faltante: str | None = None):
        self.faltante = faltante
        self.llamadas = 0

    def cargar(self, nombre, alias):
        self.llamadas += 1
        if nombre == self.faltante:
            raise RuntimeError("RESOURCE_DOES_NOT_EXIST")
        if nombre == "intencion":
            return ModeloCargado(
                "intencion",
                modelo_intencion(),
                str(self.llamadas),
                "run1",
                {"f1_macro_groupkfold": 0.92},
                {
                    "referencia_drift": {
                        "largo_descripcion": drift.referencia_numerica(np.array([20.0, 25, 30, 35, 40] * 20)),
                        "categoria_predicha": drift.referencia_categorica(
                            ["cancelacion", "facturacion"] * 50
                        ),
                    }
                },
            )
        modelo, referencia = modelo_churn()
        return ModeloCargado(
            "churn",
            modelo,
            "1",
            "run2",
            {"auc": 0.708},
            {"referencia_drift": referencia, "umbrales_nivel": {"alto": 0.6, "medio": 0.4}},
        )


@pytest.fixture
def cliente():
    with TestClient(crear_app(Settings(), CargadorFalso(), mongomock.MongoClient()["x"])) as c:
        yield c


def test_intencion_con_probabilidades_y_registro_sin_texto(cliente):
    r = cliente.post("/intencion", json={"texto": "quiero cancelar mi internet, mi CC es 1023456789"}).json()
    assert (
        r["intencion"] == "cancelacion"
        and 0 < r["confianza"] <= 1
        and set(r["probabilidades"]) >= {"cancelacion"}
    )
    assert r["version"] == "1" and r["ms"] >= 0 and isinstance(r["confiable"], bool)
    doc = cliente.app.state.db["ml_inferencias"].find_one({"modelo": "intencion"})
    assert "1023456789" not in str(doc) and doc["entrada"] == {"largo_descripcion": 48}


def test_churn_por_caracteristicas_con_nivel_y_factores(cliente):
    alto = {"dias_mora": 80.0, "tipo_servicio": "hogar"}
    r = cliente.post("/churn", json={"caracteristicas": alto}).json()
    assert r["nivel"] == "alto" and r["probabilidad"] > 0.6 and r["factores"][0]["variable"] == "dias_mora"
    assert "metodo_pago" in r["variables_imputadas"] and "no decide" in r["uso"]
    assert cliente.post("/churn", json={"caracteristicas": {"dias_mora": 0.0}}).json()["nivel"] == "bajo"


def test_desde_ficha_del_crm():
    from datetime import date

    ficha = {
        "cliente_id": "C-1013",
        "valor_mensual_total": 139900,
        "antiguedad_meses": 26,
        "dias_mora": 0,
        "servicios": [{"tipo": "hogar", "estado": "activo"}, {"tipo": "movil", "estado": "activo"}],
        "tickets_recientes": [
            {"fecha": "2026-11-13", "categoria": "soporte_tecnico"},
            {"fecha": "2026-10-30", "categoria": "facturacion"},
            {"fecha": "2026-01-01", "categoria": "soporte_tecnico"},
        ],
        "ofertas_retencion_12m": [{"fecha": "2026-03-01"}],
    }
    v = caracteristicas.desde_ficha(ficha, date.fromisoformat(HOY))
    assert v["tipo_servicio"] == "convergente" and v["tickets_90d"] == 2 and v["tickets_tecnicos_90d"] == 1
    assert v["ofertas_retencion_12m"] == 1.0 and v["valor_mensual"] == 139900.0 and v["nps_ultimo"] is None
    assert (
        caracteristicas.desde_ficha(
            {"servicios": [{"tipo": "movil"}], "valor_mensual_total": "x"}, date.fromisoformat(HOY)
        )["valor_mensual"]
        is None
    )


def test_churn_desde_ficha(cliente):
    ficha = {
        "cliente_id": "C-1003",
        "valor_mensual_total": 49900,
        "antiguedad_meses": 79,
        "dias_mora": 56,
        "servicios": [{"tipo": "movil", "estado": "activo"}],
        "tickets_recientes": [],
        "ofertas_retencion_12m": [],
    }
    r = cliente.post("/churn/ficha", json={"ficha": ficha}).json()
    assert r["cliente_id"] == "C-1003" and r["origen"] == "ficha_crm" and r["nivel"] in ("alto", "medio")


def test_drift_detecta_cambio_y_muestras(cliente):
    for mora in [85.0] * 40:  # población actual muy distinta a la de entrenamiento
        cliente.post("/churn", json={"caracteristicas": {"dias_mora": mora, "tipo_servicio": "hogar"}})
    r = cliente.get("/drift", params={"modelo": "churn"}).json()
    assert r["inferencias"] == 40 and r["alerta"] and "dias_mora" in r["variables_con_drift"]
    assert r["psi"]["valor_mensual"] is None  # sin datos en la muestra actual (todo imputado)
    muestras = cliente.get("/drift/muestras", params={"modelo": "churn"}).json()
    assert len(muestras) == 40 and muestras[0]["dias_mora"] == 85.0
    assert cliente.get("/drift", params={"modelo": "intencion"}).json()["inferencias"] == 0


def test_modelo_faltante_degrada_sin_tumbar_el_servicio():
    with TestClient(
        crear_app(Settings(), CargadorFalso(faltante="churn"), mongomock.MongoClient()["x"])
    ) as c:
        h = c.get("/health").json()
        assert h["estado"] == "degradado" and "churn" in h["errores"] and "intencion" in h["modelos"]
        assert c.post("/churn", json={"caracteristicas": {}}).status_code == 503
        assert c.post("/intencion", json={"texto": "hola"}).status_code == 200
        assert c.get("/health/vivo").json() == {"estado": "ok"}


def test_recargar_toma_la_version_nueva(cliente):
    assert cliente.get("/health").json()["modelos"]["intencion"]["version"] == "1"
    r = cliente.post("/modelos/recargar").json()
    assert r["modelos"]["intencion"]["version"] == "3"  # el cargador falso numera por llamada


def test_psi_identico_al_de_entrenamiento():
    original = Path(__file__).resolve().parents[3] / "ml" / "src" / "copiloto_ml" / "drift.py"
    if not original.is_file():
        pytest.skip("monorepo incompleto")
    assert Path(drift.__file__).read_bytes() == original.read_bytes()
    spec = importlib.util.spec_from_file_location("drift_ml", original)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ref = mod.referencia_numerica(np.arange(100, dtype=float))
    assert drift.psi(ref, list(range(50, 150))) == mod.psi(ref, list(range(50, 150)))
