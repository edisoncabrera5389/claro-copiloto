# Entrenamiento y experimentos de ML

**Tecnología:** Python 3.12 · scikit-learn 1.9 · MLflow 3.18 (Model Registry) · Evidently 0.7
**Fases del caso:** 9
**Estado:** ✅ intención y churn entrenados, comparados, registrados y en producción vía [ml-service](../apps/ml-service/)

## Qué hace

| Paso | Módulo | Detalle |
|---|---|---|
| Limpieza | `datos.py` | Duplicados (20 tickets, 12 clientes), voto mayoritario por descripción (16 descripciones con etiquetas contradictorias), atípicos a NaN (antigüedad < 0, valor ≤ 0, uso > 500 GB), conteo de nulos (NPS, ciudad) |
| Intención | `intencion.py` | 4 candidatos con **GroupKFold por descripción** (sin fuga) |
| Churn | `churn.py` | 3 candidatos con StratifiedKFold(5): AUC, PR-AUC, Brier, umbrales por percentil y coeficientes |
| Registro | `registro.py` | MLflow: parámetros, métricas, artefactos, firma, serialización **skops** con tipos de confianza explícitos; alias `staging` y promoción a `produccion` |
| Drift | `drift.py` · `reporte_drift.py` | Referencia PSI por variable (la usa el ml-service) e informe visual Evidently |
| SVM vs LLM | `comparacion_llm.py` | F1, latencia y costo del SVM, el LLM zero-shot y la cascada que usa la API |

## Ejecución

Requiere `docker compose up -d mlflow` (UI en http://localhost:5000) y los insumos en `data/raw/03_datos`.

```powershell
cd ml
uv sync
uv run python -m copiloto_ml entrenar                      # intención + churn → MLflow (staging y, si pasa el gate, produccion)
uv run python -m copiloto_ml entrenar --modelo churn --sin-mlflow   # solo métricas, sin registrar
$env:LITELLM_MASTER_KEY="<de .env>"; uv run python -m copiloto_ml comparar-llm   # ~US$ 0,01
uv run python -m copiloto_ml reporte-drift                 # → ml/reportes/drift_churn_<fecha>.html (no versionado)
```

Después de promover una versión: `curl -X POST localhost:8001/modelos/recargar` (el ml-service la toma sin reiniciar).

## Resultados

### Intención (tickets.csv, 3.816 filas · 164 descripciones únicas)

| Modelo | F1 macro GroupKFold | |
|---|---|---|
| **SVM lineal calibrado** (TF-IDF char_wb 3–5) | **0,923** | campeón |
| Regresión logística | 0,906 | |
| Naive Bayes (Complement) | 0,800 | |
| Random Forest | 0,746 | |
| *SVM con split aleatorio (con fuga)* | *1,000* | *no se usa para decidir* |

**La fuga, demostrada:** con un split aleatorio la misma descripción cae en entrenamiento y prueba, y el F1
sube a 1,000 (memoriza). GroupKFold por descripción garantiza que cada nota se evalúe con un modelo que
nunca la vio. La prueba `test_groupkfold_no_tiene_fuga_y_el_split_aleatorio_si` lo verifica.

> ⚠️ **Diferencia con el SAD:** la tabla del SAD reporta 0,83 para la regresión logística; con la limpieza
> final (voto mayoritario + deduplicación) da 0,906. El SVM sigue siendo el mejor y la decisión no cambia.

### SVM vs LLM (las 164 notas únicas, cada una cuenta una vez)

| Enfoque | F1 macro | Latencia p50 | Costo / 1.000 notas |
|---|---|---|---|
| SVM | 0,725 | 2 ms | US$ 0 |
| LLM zero-shot (gpt-4.1-mini) | 0,936 | 610 ms | US$ 0,041 |
| **Cascada: SVM si confianza ≥ 0,7; si no, LLM** | **0,917** | ~2 ms en el 92 % | **US$ 0,003** |

- Este F1 es más exigente que el de GroupKFold por ticket: mide la **generalización a redacciones nuevas**
  (solo hay 6 notas únicas de cancelación y 7 de planes). Ahí el LLM generaliza mejor.
- Con la cascada, el 92 % de las notas se resuelve con el SVM (exactitud 96,7 % cuando está seguro) y solo
  el 7,9 % va al LLM: casi el F1 del LLM a 1/13 del costo y sin latencia en la mayoría.
- **Decisión implementada en la API:** sin cliente, la llamada LLM de alcance ya existe; si el SVM duda,
  esa misma llamada usa el prompt clasificador completo (intención + alcance) → sin latencia adicional.
  Con cliente, si el SVM duda se usan reglas (para no sumar una llamada).
- **Fine-tuning (siguiente paso, no ejecutado):** con 164 notas únicas no hay datos suficientes para un
  fine-tuning que supere al zero-shot. Plan: acumular notas reales etiquetadas por el feedback del asesor
  (colección `feedback` en Mongo), y con ≥ 1.000 notas únicas comparar gpt-4.1-mini con fine-tuning vs la
  cascada en F1, costo y latencia.

### Churn (clientes_churn.csv, 3.000 clientes tras deduplicar · tasa base 15 %)

| Modelo | AUC | PR-AUC | Brier |
|---|---|---|---|
| **Regresión logística** (C = 0,5, balanceada) | **0,708 ± 0,028** | 0,349 | 0,211 |
| Random Forest | 0,679 | 0,320 | 0,198 |
| HistGradientBoosting | 0,654 | 0,288 | 0,201 |

- **No alcanza la meta de negocio (AUC 0,75):** se reporta tal cual y el modelo se usa **solo como señal de
  priorización** (nivel alto ≥ p80, medio ≥ p50) con sus factores explicativos; nunca decide la elegibilidad,
  que sigue siendo POL-RET-2026 en código (skill `evaluarRetencion`).
- Agregados de tickets.csv por cliente **no mejoran** el AUC (0,708 → 0,708):
  descartados para no agregar complejidad.
- Siguiente paso: variables de comportamiento que el dataset no trae (uso diario, caídas reales, NPS
  reciente) y recalibrar con datos de producción.

## Política de promoción (Model Registry)

1. Cada entrenamiento registra una versión nueva con alias **`staging`**.
2. Pasa a **`produccion`** solo si supera el gate técnico (**F1 ≥ 0,80** intención, **AUC ≥ 0,65** churn) **y**
   es igual o mejor que el campeón actual en la métrica principal.
3. El ml-service carga siempre `models:/<nombre>@produccion`; `POST /modelos/recargar` aplica el cambio en caliente.
4. Rollback: mover el alias `produccion` a la versión anterior en la UI de MLflow y recargar.

## Drift

- **PSI por variable** (en el ml-service, `GET /drift?modelo=`): < 0,1 estable · 0,1–0,2 moderado · **> 0,2 alerta**.
  Las inferencias se guardan en Mongo sin texto libre (solo largo de la nota y clase predicha).
- **Hallazgo en la demo:** el PSI de intención alerta (largo de la nota 4,8) porque las preguntas del asesor
  son más largas que las notas de tickets con que se entrenó: drift real de dominio, que respalda la cascada
  con el LLM y el plan de reentrenar con notas reales.
- Informe Evidently de churn: excluye las variables que el CRM de la demo no entrega (NPS, uso de datos,
  caídas, método de pago); el modelo las imputa igual que en el entrenamiento.

## Pruebas

```powershell
uv run pytest      # 8 pruebas: limpieza, GroupKFold vs fuga, churn, PSI, promoción en MLflow (sqlite temporal) y corpus real
uv run ruff check . ; uv run ruff format --check .
```

La prueba sobre el corpus real reproduce los hallazgos (se omite si no están los insumos).
