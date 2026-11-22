# Servicio de modelos de ML

**Tecnología:** Python 3.12 · FastAPI · scikit-learn 1.9 · mlflow-skinny 3.18 · skops · MongoDB
**Fases del caso:** 9
**Estado:** ✅ intención (SVM) y churn (regresión logística) servidos desde el Model Registry, con drift PSI

## Propósito

Sirve los modelos que entrena [`ml/`](../../ml/) y que MLflow promueve con el alias `produccion`. La API del
agente lo usa para:

- **Intención** (`POST /intencion`): primer paso de la cascada SVM → LLM, en milisegundos. Si la confianza
  calibrada es < 0,7, la API decide con el clasificador LLM o con reglas (ver `ml/README.md`).
- **Riesgo de churn** (`POST /churn/ficha`): en la ruta de retención recibe la ficha del CRM (ya sin PII,
  tal como la entrega el MCP), arma las variables y devuelve probabilidad, nivel (alto/medio/bajo) y los
  factores que más empujan el riesgo. **Es una señal de priorización**: la elegibilidad la decide POL-RET-2026.

Si MLflow no responde o falta un modelo, el servicio arranca igual, lo informa en `/health` (estado
`degradado`) y la API sigue con su respaldo. **La API nunca depende de él para responder.**

## Endpoints

| Método y ruta | Uso |
|---|---|
| `POST /intencion` `{"texto"}` | Clase, confianza, probabilidades por clase, versión del modelo y ms |
| `POST /churn` `{"caracteristicas"}` | Riesgo a partir de las variables del modelo (las faltantes se imputan) |
| `POST /churn/ficha` `{"ficha"}` | Igual, a partir de la ficha del CRM (lo que usa la API) |
| `GET /drift?modelo=churn\|intencion` | PSI por variable sobre las últimas 500 inferencias; alerta si > 0,2 |
| `GET /drift/muestras?modelo=` | Inferencias guardadas (para el informe Evidently de `ml/`) |
| `POST /modelos/recargar` | Toma en caliente la versión recién promovida en MLflow |
| `GET /metrics` | Prometheus: inferencias por modelo y resultado, latencia, confianza del SVM (fracción que va al LLM) y **PSI por variable** recalculado en cada lectura |
| `GET /health` · `GET /health/vivo` | Versiones y métricas principales de cada modelo · liveness |

**PII:** nunca se registra ni se guarda el texto de la nota; en logs y en Mongo solo van su largo y la clase
predicha. Para churn solo se guardan las variables numéricas y categóricas del modelo.

## Ejecución

```powershell
docker compose up -d mlflow ml-service      # requiere haber entrenado: ver ml/README.md
curl localhost:8001/health
curl -X POST localhost:8001/intencion -H "Content-Type: application/json" -d '{\"texto\": \"quiere portar su número\"}'
```

Local, sin Docker: `uv sync` y `uv run python -m copiloto_ml_service` (puerto 8001), con
`ML_MLFLOW_TRACKING_URI=http://127.0.0.1:5000` y `ML_MONGO_URL=mongodb://127.0.0.1:27017`.

| Variable | Defecto | |
|---|---|---|
| `ML_MLFLOW_TRACKING_URI` | `http://mlflow:5000` | Tracking + registry |
| `ML_ALIAS` | `produccion` | Alias que se carga |
| `ML_MONGO_URL` | `mongodb://mongo:27017` | Inferencias para drift |
| `ML_FECHA_REFERENCIA` | `2026-11-18` | "Hoy" del caso (ventanas de 90 días y 12 meses) |
| `ML_UMBRAL_CONFIANZA` | `0.7` | Marca `confiable` en la respuesta de intención |

Imagen: multi-stage, usuario no root (uid 10001), sistema de archivos de solo lectura, healthcheck en
`/health/vivo`. Medido: intención en ~7 ms dentro del contenedor.

## Drift en producción

- Las variables que el CRM no entrega (NPS, uso de datos, caídas, método de pago) llegan vacías: se informan como **sin datos**, no como drift. Antes `metodo_pago` daba PSI 17 (todo "desconocido"), una falsa alarma vista en el tablero.
- En la demo, el churn sí muestra drift real: las inferencias salen de 4 clientes consultados una y otra vez, que no se parecen a la población de entrenamiento. La intención también (las preguntas del asesor son más largas que las notas de tickets). La alerta `DriftDeModelo` exige ≥ 30 inferencias en la ventana.

## Pruebas

```powershell
uv run pytest      # 10 pruebas con un cargador falso (sin MLflow) y mongomock · cobertura 92 %
uv run ruff check . ; uv run ruff format --check .
```

`drift.py` es copia exacta del de `ml/`: una prueba de contrato verifica que no diverjan.
