"""Registro en MLflow con promoción controlada (champion / challenger).

Cada entrenamiento crea una versión del modelo con alias `staging`. Pasa a `produccion` solo si:
1. supera el umbral técnico (gate) del modelo, y
2. iguala o supera la métrica del campeón actual en `produccion`.
MLflow 3 reemplaza las "stages" (Staging/Production del SAD) por alias: misma semántica.
"""

import json
import tempfile
from pathlib import Path
from typing import Any

import mlflow
from mlflow import MlflowClient
from mlflow.models import infer_signature


def requisitos() -> list[str]:
    """Versiones exactas con las que se entrenó: el ml-service debe cargar el modelo con las mismas (y así
    MLflow no intenta deducir el entorno, que tardaba ~15 s por modelo)."""
    from importlib.metadata import version

    return [f"{p}=={version(p)}" for p in ("scikit-learn", "pandas", "numpy")]


PERMITIDOS = {"numpy.dtype"}  # lo usa OneHotEncoder(dtype=...): un tipo de datos, no ejecuta código


def tipos_confiables(modelo: Any) -> list[str]:
    """MLflow 3 serializa con skops (no ejecuta código al cargar, a diferencia de pickle) y exige declarar
    los tipos no estándar. Solo se aceptan clases de scikit-learn: cualquier otra cosa detiene el registro."""
    import skops.io as sio

    tipos = sio.get_untrusted_types(data=sio.dumps(modelo))
    ajenos = [t for t in tipos if not t.startswith("sklearn.") and t not in PERMITIDOS]
    if ajenos:
        raise ValueError(f"El modelo contiene tipos no confiables: {ajenos}")
    return tipos


def metrica_campeon(cliente: MlflowClient, modelo: str, metrica: str) -> float | None:
    try:
        version = cliente.get_model_version_by_alias(modelo, "produccion")
    except mlflow.exceptions.MlflowException:
        return None
    run = cliente.get_run(version.run_id)
    return run.data.metrics.get(metrica)


def registrar(
    nombre: str,
    modelo: Any,
    entrada_ejemplo: Any,
    metricas: dict[str, float],
    parametros: dict[str, Any],
    artefactos: dict[str, Any],
    metrica_gate: str,
    umbral_gate: float,
    experimento: str,
) -> dict[str, Any]:
    mlflow.set_experiment(experimento)
    cliente = MlflowClient()
    campeon = metrica_campeon(cliente, nombre, metrica_gate)
    with mlflow.start_run(run_name=f"{nombre}-{parametros.get('algoritmo', '')}") as run:
        mlflow.log_params(parametros)
        mlflow.log_metrics(metricas)
        with tempfile.TemporaryDirectory() as tmp:
            for archivo, contenido in artefactos.items():
                ruta = Path(tmp) / archivo
                ruta.write_text(
                    json.dumps(contenido, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
                )
                mlflow.log_artifact(str(ruta))
        salida = modelo.predict_proba(entrada_ejemplo)
        info = mlflow.sklearn.log_model(
            modelo,
            name="modelo",
            signature=infer_signature(entrada_ejemplo, salida),
            input_example=entrada_ejemplo,
            registered_model_name=nombre,
            pip_requirements=requisitos(),
            skops_trusted_types=tipos_confiables(modelo),
        )
    version = info.registered_model_version
    cliente.set_registered_model_alias(nombre, "staging", version)
    valor = metricas[metrica_gate]
    pasa_gate = valor >= umbral_gate
    mejora = campeon is None or valor >= campeon
    promovido = pasa_gate and mejora
    if promovido:
        cliente.set_registered_model_alias(nombre, "produccion", version)
    cliente.set_model_version_tag(
        nombre, version, "gate", f"{metrica_gate}={valor:.3f} (umbral {umbral_gate})"
    )
    return {
        "modelo": nombre,
        "version": version,
        "run_id": run.info.run_id,
        metrica_gate: round(valor, 4),
        "campeon_anterior": campeon,
        "pasa_gate": pasa_gate,
        "promovido_a_produccion": promovido,
    }
