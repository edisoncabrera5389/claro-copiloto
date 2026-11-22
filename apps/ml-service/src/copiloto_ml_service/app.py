"""API del servicio de modelos.

POST /intencion · POST /churn · POST /churn/ficha · GET /drift · GET /drift/muestras ·
POST /modelos/recargar · GET /health
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from copiloto_ml_service import caracteristicas, drift
from copiloto_ml_service.config import Settings
from copiloto_ml_service.modelos import Cargador, CargadorMLflow, ModeloCargado, cargar_todos

log = logging.getLogger("copiloto_ml_service")
NombreModelo = Annotated[Literal["churn", "intencion"], Query(alias="modelo")]


class Texto(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)


class Caracteristicas(BaseModel):
    caracteristicas: dict[str, Any]


class Ficha(BaseModel):
    ficha: dict[str, Any]


def crear_app(settings: Settings | None = None, cargador: Cargador | None = None, db: Any = None) -> FastAPI:
    s = settings or Settings()

    @asynccontextmanager
    async def ciclo(app: FastAPI):
        app.state.cargador = cargador or CargadorMLflow(s.mlflow_tracking_uri)
        app.state.modelos, app.state.errores = await asyncio.to_thread(
            cargar_todos, app.state.cargador, s.alias
        )
        if db is not None:
            app.state.db = db
        else:  # pragma: no cover - conexión real
            from pymongo import MongoClient

            app.state.db = MongoClient(s.mongo_url, serverSelectionTimeoutMS=3000)[s.mongo_db]
        yield

    app = FastAPI(title="Claro Copiloto · ML service", version="0.1.0", lifespan=ciclo)

    def modelo(request: Request, nombre: str) -> ModeloCargado:
        m = request.app.state.modelos.get(nombre)
        if m is None:
            raise HTTPException(
                503, f"Modelo {nombre} no disponible: {request.app.state.errores.get(nombre, '?')}"
            )
        return m

    async def registrar(request: Request, nombre: str, version: str, entrada: dict, salida: dict) -> None:
        """Inferencias para el monitoreo de drift. Nunca el texto libre (puede tener PII): solo derivados."""
        doc = {
            "modelo": nombre,
            "version": version,
            "entrada": entrada,
            "salida": salida,
            "fecha": datetime.now(UTC),
        }
        try:
            await asyncio.to_thread(request.app.state.db["ml_inferencias"].insert_one, doc)
        except Exception as e:  # noqa: BLE001 - el registro no debe tumbar la predicción
            log.warning("No se pudo registrar la inferencia: %s", type(e).__name__)

    @app.post("/intencion")
    async def intencion(t: Texto, request: Request) -> dict[str, Any]:
        m = modelo(request, "intencion")
        inicio = time.perf_counter()
        prob = m.modelo.predict_proba([t.texto])[0]
        clases = list(m.modelo.classes_)
        i = int(prob.argmax())
        resultado = {
            "intencion": clases[i],
            "confianza": round(float(prob[i]), 4),
            "probabilidades": {c: round(float(p), 4) for c, p in zip(clases, prob, strict=True)},
            "confiable": bool(prob[i] >= s.umbral_confianza),
            "version": m.version,
            "ms": round((time.perf_counter() - inicio) * 1000, 2),
        }
        await registrar(
            request,
            "intencion",
            m.version,
            {"largo_descripcion": len(t.texto)},
            {"categoria_predicha": resultado["intencion"], "confianza": resultado["confianza"]},
        )
        return resultado

    async def puntuar(request: Request, valores: dict[str, Any], origen: str) -> dict[str, Any]:
        m = modelo(request, "churn")
        fila = pd.DataFrame([{c: valores.get(c) for c in caracteristicas.COLUMNAS}])
        fila[caracteristicas.NUMERICAS] = fila[caracteristicas.NUMERICAS].astype("float64")
        prob = float(m.modelo.predict_proba(fila)[0, 1])
        umbral = m.artefactos.get("umbrales_nivel", {"alto": 0.6, "medio": 0.43})
        nivel = "alto" if prob >= umbral["alto"] else "medio" if prob >= umbral["medio"] else "bajo"
        faltantes = [c for c in caracteristicas.COLUMNAS if valores.get(c) is None]
        resultado = {
            "probabilidad": round(prob, 4),
            "nivel": nivel,
            "umbrales": umbral,
            "factores": caracteristicas.factores(m.modelo, fila),
            "variables_imputadas": faltantes,
            "version": m.version,
            "auc_validacion": round(m.metricas.get("auc", 0.0), 3),
            "origen": origen,
            "uso": "Señal de priorización (AUC bajo la meta de 0,75): no decide elegibilidad.",
        }
        await registrar(
            request,
            "churn",
            m.version,
            {c: valores.get(c) for c in caracteristicas.COLUMNAS},
            {"probabilidad": resultado["probabilidad"], "nivel": nivel},
        )
        return resultado

    @app.post("/churn")
    async def churn(c: Caracteristicas, request: Request) -> dict[str, Any]:
        return await puntuar(request, c.caracteristicas, "caracteristicas")

    @app.post("/churn/ficha")
    async def churn_ficha(f: Ficha, request: Request) -> dict[str, Any]:
        """Para la API del agente: recibe la ficha del CRM (sin PII) y arma las variables aquí."""
        valores = caracteristicas.desde_ficha(f.ficha, s.fecha_referencia)
        return await puntuar(request, valores, "ficha_crm") | {"cliente_id": f.ficha.get("cliente_id")}

    def inferencias(request: Request, nombre: str, limite: int) -> list[dict[str, Any]]:
        cursor = request.app.state.db["ml_inferencias"].find({"modelo": nombre}, {"_id": 0}).sort("fecha", -1)
        return list(cursor.limit(limite))

    @app.get("/drift")
    async def calcular_drift(request: Request, modelo_nombre: NombreModelo = "churn") -> dict:
        """PSI por variable: inferencias recientes vs distribución de entrenamiento (> 0,2 → alerta)."""
        m = modelo(request, modelo_nombre)
        docs = await asyncio.to_thread(inferencias, request, modelo_nombre, s.ventana_drift)
        referencia = m.artefactos.get("referencia_drift", {})
        filas = [d["entrada"] | d["salida"] for d in docs]
        variables = {}
        for nombre, ref in referencia.items():
            valores = [f.get(nombre) for f in filas]
            if ref["tipo"] == "categorica":
                valores = ["desconocido" if v is None else v for v in valores]
            valor = drift.psi(ref, valores)
            variables[nombre] = None if valor is None else round(valor, 4)
        alertas = [k for k, v in variables.items() if v is not None and v > drift.UMBRAL_ALERTA]
        return {
            "modelo": modelo_nombre,
            "version": m.version,
            "inferencias": len(filas),
            "psi": variables,
            "umbral_alerta": drift.UMBRAL_ALERTA,
            "variables_con_drift": alertas,
            "alerta": bool(alertas),
        }

    @app.get("/drift/muestras")
    async def muestras(
        request: Request, modelo_nombre: NombreModelo = "churn", limite: int = 1000
    ) -> list[dict]:
        docs = await asyncio.to_thread(inferencias, request, modelo_nombre, min(limite, 5000))
        return [d["entrada"] for d in docs]

    @app.post("/modelos/recargar")
    async def recargar(request: Request) -> dict[str, Any]:
        """Toma la versión que tenga hoy el alias en MLflow (tras una promoción), sin reiniciar."""
        request.app.state.modelos, request.app.state.errores = await asyncio.to_thread(
            cargar_todos, request.app.state.cargador, s.alias
        )
        return await health(request)

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        return {
            "estado": "ok" if not request.app.state.errores else "degradado",
            "alias": s.alias,
            "modelos": {n: m.info() for n, m in request.app.state.modelos.items()},
            "errores": request.app.state.errores,
        }

    @app.get("/health/vivo")
    async def vivo() -> dict[str, str]:
        return {"estado": "ok"}

    return app
