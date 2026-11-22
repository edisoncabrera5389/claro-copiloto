# Infraestructura

**Tecnología:** Terraform · LiteLLM · OpenTelemetry · Phoenix · Prometheus · Alertmanager · Grafana · n8n
**Fases del caso:** 10, 11, 13
**Estado:** ✅ LiteLLM, observabilidad y RPA · ⏳ Terraform (bloque `feat/terraform`)

| Carpeta | Contenido |
|---|---|
| `litellm/` | ✅ [config.yaml](litellm/config.yaml) del proxy LiteLLM 1.110.2 (puerto 4000): alias `economico` (gpt-4.1-mini), `alto` (gpt-4.1), `embedding` (text-embedding-3-small) y `local` (Ollama llama3.2:3b, perfil `llm-local`); fallback alto → economico → local, reintentos, enfriamiento por fallas y sin registro de mensajes |
| `observability/prometheus/` | ✅ Scrape de api, ml-service, ingesta-worker y n8n · [12 reglas de alerta](observability/prometheus/alertas.yml) con las metas del caso · [pruebas unitarias](observability/prometheus/alertas_test.yml) con `promtool` |
| `observability/alertmanager/` | ✅ Enruta las alertas al webhook de n8n |
| `observability/grafana/` | ✅ Datasources y 2 tableros **como código** ([generar_tableros.py](observability/grafana/generar_tableros.py) → `dashboards/*.json`, provisionados de solo lectura) |
| `n8n/flujos/` | ✅ 3 flujos versionados que se importan y publican en cada arranque |
| `terraform/` | ⏳ Módulos Azure y ambientes dev/prod |

## Observabilidad (SAD 2.10)

| Pregunta | Dónde se ve |
|---|---|
| ¿Qué hizo el agente en este turno, con qué fuentes, tools, tokens y prompt? | **Phoenix** http://localhost:6006 → proyecto `claro-copiloto`: span `turno` → nodos del grafo → búsqueda (fuente y versión de cada fragmento) → tools → LLM. El `trace_id` está en la auditoría de MongoDB |
| ¿Cumplimos las metas (p95, sin cita, éxito de tools, costo, 👍)? | **Grafana** http://localhost:3000 → *Copiloto · Agente y operación* (lectura anónima; admin con `GRAFANA_ADMIN_PASSWORD`) |
| ¿Drift de los modelos, cascada SVM → LLM, frescura de la ingesta, flujos RPA? | Grafana → *Copiloto · ML, ingesta y RPA* |
| ¿Qué alertas están activas y qué se hizo con ellas? | Tabla "Alertas disparadas" en Grafana · Prometheus http://localhost:9090/alerts · ejecuciones del flujo *Alertas → acción* en n8n |

**Alertas** (umbral = meta del caso): primer token p95 > 2 s · errores de tools > 10 % · bucles · acciones bloqueadas
(posible abuso) · sin cita > 5 % · 👎 > 30 % · costo > US$ 2/h · turnos con error · drift PSI > 0,2 · frescura
> 15 min · dead-letter · servicio caído.

**PII:** las trazas llevan el texto enmascarado que ve el LLM y los nombres (no valores) de los argumentos de las
tools; los logs de Nginx, sin query ni cuerpo; `/api/metrics` no se expone hacia el navegador.

**Medido al montar el bloque:** MLflow 3 usaba 2,25 GB de RAM por 8 consumidores de trabajos GenAI que no usamos →
`MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false` y un worker: 428 MB. Así cabe el stack de observabilidad (~1,2 GB) en la
máquina de demo.

## RPA con n8n (http://localhost:5678)

| Flujo | Disparo | Efecto |
|---|---|---|
| **Acción confirmada → ERP** | La API al confirmarse una propuesta | Visita técnica prioritaria → **orden de servicio** en el ERP (24 h, con el ticket); ajuste de factura → **nota crédito** (idempotente por `ajuste_id`). Reintenta 3 veces ante 429/503 |
| **Escalamiento → notificación** | Escalamiento manual o por política | Prepara el aviso al supervisor (SLA 10 min). Local: queda en las ejecuciones; producción: nodo de Teams/correo |
| **Alertas → acción** | Alertmanager | Drift → solicitud de reentrenamiento (producción: `workflow_dispatch` del pipeline de ML); críticas → guardia |

Los flujos se versionan en `n8n/flujos/*.json` y el contenedor los importa y publica al arrancar
(`import:workflow` + `publish:workflow`: en n8n 2.x el modo estándar no acepta `--activeState`). La API key del ERP se lee
del entorno (`MOCKS_API_KEY`), no del JSON. La primera vez, la UI pide crear el usuario dueño (solo para ver
ejecuciones; los webhooks funcionan sin él).

## Pruebas

```powershell
py -3.13 scripts/smoke_observabilidad.py     # 9 verificaciones: targets, reglas, traza real en Phoenix, métricas, tableros, Alertmanager, n8n
docker run --rm -v ${PWD}/infra/observability/prometheus:/p -w /p --entrypoint promtool prom/prometheus:v3.16.0 test rules alertas_test.yml
py -3.13 infra/observability/grafana/generar_tableros.py   # regenerar los tableros tras cambiarlos
```

Terraform (siguiente bloque): `terraform validate`, `terraform test` con mocks, tflint y checkov.
