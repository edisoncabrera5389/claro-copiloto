"""Carga de modelos desde el Model Registry de MLflow (alias `produccion`) con sus artefactos.

Se puede recargar en caliente (POST /modelos/recargar): al promover una versión nueva en MLflow, el servicio
la toma sin reiniciar. Si MLflow no responde o el modelo aún no se entrenó, el servicio arranca igual y lo
informa en /health (la API usa su respaldo).
"""

import json
import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger("copiloto_ml_service")
MODELOS = ("intencion", "churn")
METRICAS_PRINCIPALES = {
    "f1_macro_groupkfold",
    "f1_macro_std",
    "f1_macro_split_aleatorio_con_fuga",
    "auc",
    "auc_std",
    "pr_auc",
    "brier",
    "tasa_base",
}
ARTEFACTOS = {
    "intencion": ["referencia_drift.json"],
    "churn": ["referencia_drift.json", "umbrales_nivel.json", "coeficientes.json"],
}


@dataclass
class ModeloCargado:
    nombre: str
    modelo: Any
    version: str
    run_id: str
    metricas: dict[str, float] = field(default_factory=dict)
    artefactos: dict[str, Any] = field(default_factory=dict)

    def info(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "run_id": self.run_id,
            "metricas": {k: round(v, 4) for k, v in self.metricas.items() if k in METRICAS_PRINCIPALES},
        }


class Cargador(Protocol):
    def cargar(self, nombre: str, alias: str) -> ModeloCargado: ...


class CargadorMLflow:
    def __init__(self, tracking_uri: str):
        import mlflow

        mlflow.set_tracking_uri(tracking_uri)
        self._uri = tracking_uri

    def cargar(self, nombre: str, alias: str) -> ModeloCargado:
        import mlflow.sklearn
        from mlflow import MlflowClient

        cliente = MlflowClient(self._uri)
        version = cliente.get_model_version_by_alias(nombre, alias)
        modelo = mlflow.sklearn.load_model(f"models:/{nombre}@{alias}")
        artefactos = {}
        with tempfile.TemporaryDirectory() as tmp:
            for archivo in ARTEFACTOS[nombre]:
                ruta = cliente.download_artifacts(version.run_id, archivo, tmp)
                artefactos[archivo.removesuffix(".json")] = json.loads(Path(ruta).read_text(encoding="utf-8"))
        metricas = cliente.get_run(version.run_id).data.metrics
        return ModeloCargado(nombre, modelo, str(version.version), version.run_id, metricas, artefactos)


def cargar_todos(cargador: Cargador, alias: str) -> tuple[dict[str, ModeloCargado], dict[str, str]]:
    modelos, errores = {}, {}
    for nombre in MODELOS:
        try:
            modelos[nombre] = cargador.cargar(nombre, alias)
            log.info(
                json.dumps({"evento": "modelo_cargado", "modelo": nombre, "version": modelos[nombre].version})
            )
        except Exception as e:  # noqa: BLE001 - el servicio debe arrancar aunque falte un modelo
            errores[nombre] = f"{type(e).__name__}: {str(e)[:200]}"
            log.warning(
                json.dumps({"evento": "modelo_no_disponible", "modelo": nombre, "error": errores[nombre]})
            )
    return modelos, errores
