# Evaluación del RAG y del agente (LLMOps)

**Tecnología:** Python (librería estándar) · LiteLLM como juez  
**Fases del caso:** 8, 12  
**Estado:** ✅ runner del golden con LLM juez · todos los KPIs del caso en verde

[correr_golden.py](correr_golden.py) ejecuta las 30 preguntas del golden contra la API en ejecución (por SSE, para medir el TTFT real), cada una en una sesión nueva, y calcula los KPIs del caso. Los reportes (`eval/reportes/*.json|.md`) no se versionan porque contienen las preguntas del insumo.

```powershell
docker compose up -d api
py -3.13 eval/correr_golden.py                      # completa, con LLM juez (tier alto)
py -3.13 eval/correr_golden.py --sin-juez           # rápida, sin groundedness
py -3.13 eval/correr_golden.py --ids GQ-18 GQ-26    # subconjunto
```

Sale con código 1 si algún KPI no cumple su meta: listo para usarse como **gate** en CI (feat/ci-cd).

## Resultado actual (21-nov-2026 · prompt `sistema` 1.3.0 · sin reranker)

| KPI | Resultado | Meta del caso |
|---|---|---|
| Exactitud golden (puntos clave, literal o semántica con juez) | **100 %** (30/30) | ≥ 80 % |
| Exactitud literal (solo coincidencia de texto) | **86,7 %** | — |
| Groundedness (LLM juez, respuestas documentales) | **0,993** | ≥ 0,85 |
| Recall@k (fuentes del golden entre las recuperadas) | **0,982** | ≥ 0,90 |
| Respuestas sin cita | **0 %** | ≤ 5 % |
| Éxito de tareas del agente (tools esperadas) | **100 %** | ≥ 90 % |
| Acciones con efecto sin confirmación | **0** | 0 |
| p95 TTFT / p95 total | **1,89 s / 2,39 s** | ≤ 2 s / ≤ 8 s |
| Costo promedio por pregunta | **US$ 0,0025** | < US$ 0,02 por conversación |

Las 4 preguntas que pasan solo por la verificación semántica difieren en redacción, no en contenido (ej. el golden espera "no se puede negar" y la respuesta dice "no se le puede negar"); ambas métricas se reportan.

## Cómo evolucionó (evidencia de la iteración guiada por evaluación)

| Corrida | Cambio | Exactitud | Recall | Sin cita | Tareas | p95 TTFT |
|---|---|---|---|---|---|---|
| 1 | Primera versión | 83,3 % | 0,875 | 10,7 % | 100 % | 2,48 s |
| 2 | Juez semántico, política precargada en retención, intención por reglas con cliente | 100 % | 0,982 | 7,1 % | 75 % | 1,91 s |
| 3 | Skill de retención determinística, citar la política (prompt 1.2.0) | 100 % | 0,982 | 0 % | 100 % | 1,70 s |
| 4 | Reranker bge-m3 activo **en CPU** | 96,7 % | 0,982 | 0 % | 100 % | **19,7 s** |
| 5 | Final (prompt 1.3.0, sin reranker) | 100 % | 0,982 | 0 % | 100 % | 1,89 s |

**Decisión sobre el reranker**: con 13 documentos la búsqueda híbrida ya ubica la fuente correcta (recall igual con y sin reranker) y el cross-encoder en CPU multiplica la latencia por 10. Queda desactivado (`API_RERANKER_ACTIVO=false`); con un corpus mayor se activaría como servicio en la GPU de la máquina (RTX 4060).

## Criterios

- **Puntos clave**: coincidencia normalizada (sin tildes, "30 %" = "30%"); si no hay coincidencia literal, el juez decide si la respuesta expresa la idea.
- **Tools**: `evaluarRetencion` y `listarServicios` cuentan como consulta de la ficha (`obtenerCliente`); una propuesta de `crearTicket` cuenta como uso de `crearTicket`.
- **Groundedness**: solo en respuestas documentales; las que usan datos de CRM/Facturación se miden por éxito de tareas (el juez no ve esos datos).
- **Recall@k**: por documento lógico (el catálogo v2 cuenta como el catálogo del golden).
