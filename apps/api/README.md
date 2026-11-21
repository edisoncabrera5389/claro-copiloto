# API y agente

**Tecnología:** Python 3.12 · FastAPI (SSE) · LangGraph · LiteLLM (gpt-4.1-mini / gpt-4.1) · Qdrant · FastMCP · Redis · MongoDB · uv  
**Fases del caso:** 4, 7, 8  
**Estado:** ✅ agente con RAG híbrido, guardrails, human-in-the-loop verificable, memoria y auditoría · golden 100 %

## Grafo del agente (LangGraph)

```
entrada (guardrails en código) ─► bloqueado (prompt injection) ─────────────────────────► rechazar
      └─► clasificar ─► fuera de alcance ───────────────────────────────────────────────► rechazar
          (+ búsqueda en paralelo)  ├─► escalar (Política de Escalamiento, numeral 2) ─► salida
                                    └─► agente (RAG + tools MCP, ≤ 6 pasos, ≤ 3 por tool) ─► salida
salida: citas validadas · confianza · "no encontrado → escalar" · PII redactada · fuentes
```

| Decisión | Por qué |
|---|---|
| **Reglas antes del LLM** | Los 7 disparadores de escalamiento obligatorio (tutela/SIC/CRC, vulnerabilidad, agresión, fraude, terceros…), la inyección y el alcance se deciden en código ([guardrails.py](src/copiloto_api/guardrails.py)) y quedan auditados con su motivo. GQ-29 responde en ~1 s citando la política |
| **Búsqueda en paralelo con la clasificación** | Para preguntas sin cliente, el retriever corre mientras se clasifica y el LLM recibe las fuentes desde la primera llamada: una ida y vuelta menos (TTFT p95 1,9 s) y respuestas siempre basadas en las fuentes |
| **Intención por reglas con cliente** | Si hay un `C-XXXX`, el tema es de atención por definición: sin llamada de clasificación (−0,6 s). El modelo SVM de `feat/ml-models` reemplaza el clasificador |
| **Skill de retención determinística** | Si el cliente quiere cancelar, `evaluarRetencion` se ejecuta siempre (no depende de que el LLM la elija) y, si la política exige visita técnica prioritaria, la propuesta de `crearTicket` se genera en código |
| **PII en bóveda** | Documento, celular y correo se reemplazan por `<DOCUMENTO_1>` antes del LLM y se restituyen solo al llamar la tool: ni el proveedor, ni las trazas, ni la auditoría ven el dato |
| **Escrituras solo sobre el cliente de la conversación** | El LLM no puede inventar el cliente ni ajustar la factura de otro titular (se verifica el dueño de la factura en Facturación). Visto en pruebas: proponía tickets sin cliente |
| **Confianza absoluta** | Similitud coseno de embeddings (o sigmoide del reranker): el puntaje RRF depende solo de la posición y el primero siempre "parece" bueno. Bajo el umbral (0,25) → "no encontré información suficiente, escala a supervisor" |
| **Reranker desactivado** | Medido: bge-reranker-v2-m3-int8 y jina-v2 tardan 2–5 s en CPU; con el reranker el p95 TTFT sube de 1,9 s a 19,7 s sin mejorar el recall (13 documentos). Configurable con `API_RERANKER_ACTIVO`; candidato a servicio en GPU si el corpus crece |
| **Ruteo multi-LLM** | `economico` para preguntas de conocimiento, `alto` cuando hay cliente o retención (multi-tool). Los nombres reales viven en [infra/litellm/config.yaml](../../infra/litellm/config.yaml) |

## Human-in-the-loop verificable (confirmación firmada)

1. El agente llama una tool de escritura **sin** token → el MCP devuelve una propuesta; la API la **guarda en Redis** y emite el evento `propuesta` con su `propuesta_id`.
2. El asesor confirma `POST /acciones/{id}/confirmar`: el cliente solo envía el id (no puede alterar parámetros). Si la propuesta exige supervisor (ajuste > $50.000), solo un supervisor puede confirmarla.
3. La API **firma** el token HMAC (mismo algoritmo que el MCP, verificado con una prueba de contrato) y llama la tool. El MCP verifica y ejecuta **una vez** (GETDEL atómico en la API + `jti` de un solo uso en el MCP).
4. Si el sistema estaba caído (circuito abierto, sin conexión), la propuesta vuelve a pendientes y se puede reintentar.

## API

| Método y ruta | Descripción |
|---|---|
| `POST /auth/login` | `{usuario, password}` → JWT (roles `asesor`, `supervisor`, `admin`; usuarios demo A-001, A-002, SUP-001, ADM-001 con `API_DEMO_PASSWORD`) |
| `POST /chat` | SSE. Eventos: `inicio`, `estado`, `token`, `reiniciar`, `tool`, `propuesta`, `reemplazar`, `fuentes`, `fin`, `error` |
| `POST /chat/sincrono` | Mismo turno en JSON (evaluación, integraciones) |
| `GET /acciones/pendientes` | Propuestas: las propias (asesor) o todas (supervisor/admin) |
| `POST /acciones/{id}/confirmar` · `/rechazar` | Confirmación por rol (ver arriba) |
| `POST /feedback` | 👍/👎 (`valor` 1 o −1) y comentario sobre un `turno_id` |
| `GET /conversaciones/{sesion}` | Historial auditado de la sesión |
| `GET /health` · `/health/vivo` | Componentes (Redis, reranker) y versiones de prompts · liveness |

El evento `fin` trae: respuesta, ruta, intención, confianza, fuentes (documento, versión, sección, relevancia, citada, extracto), tools, propuestas, modelo, tokens, costo en USD y latencias (TTFT y total).

## Memoria, auditoría y límites

- **Redis**: memoria corta por sesión (6 turnos, TTL 2 h, texto enmascarado), propuestas pendientes y límite de 30 solicitudes por minuto por usuario (429 con `Retry-After`).
- **MongoDB**: `auditoria` (pregunta enmascarada, intención, ruta, motivo, tools, fuentes con versión, modelo, versiones de prompts, tokens, costo, latencias, confianza), `acciones` (quién propuso, quién confirmó, resultado) y `feedback`.
- **Prompts versionados** en [prompts/](src/copiloto_api/prompts/) (semver con historial de cambios); la versión queda en cada turno auditado.

## Ejecución

```powershell
docker compose up -d --build api      # levanta también litellm, qdrant, redis, mongo y mcp-server
py -3.13 scripts/smoke_api.py         # 12 verificaciones de punta a punta
py -3.13 eval/correr_golden.py        # golden con LLM juez (ver eval/README.md)
```

Documentación interactiva: http://localhost:8000/docs. Variables: `JWT_SECRET`, `API_DEMO_PASSWORD`, `LITELLM_MASTER_KEY`, `MCP_CONFIRMACION_SECRET`, `API_RERANKER_ACTIVO`, `API_RATE_LIMIT_POR_MIN`, `API_UMBRAL_CONFIANZA` (ver [config.py](src/copiloto_api/config.py)). Imagen multi-stage (765 MB), usuario `10001`, raíz de solo lectura, puerto solo en `127.0.0.1`.

## Pruebas

```powershell
cd apps/api
uv run pytest            # 52 pruebas, cobertura 92 %
uv run ruff check . ; uv run ruff format --check .
```

- **Grafo** con LLM, retriever y MCP falsos: rutas (RAG, escalamiento, fuera de alcance, inyección), citas inválidas, baja confianza, PII que nunca llega al LLM, escrituras sobre otro cliente u otra factura, skill de retención y visita automática, límites de pasos y de llamadas.
- **API**: login, SSE en orden, auditoría enmascarada, confirmación con token verificado por un MCP falso que usa el algoritmo real, roles (supervisor para ajustes > $50.000, otro asesor no ve ni confirma), reintento tras falla transitoria, feedback y límite de solicitudes.
- **Contratos entre servicios**: el tokenizador BM25 es idéntico al de la ingesta y el token que firma la API lo acepta el código del MCP.
