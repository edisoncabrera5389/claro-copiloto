# 1. Planteamiento del problema

> Fecha de referencia del caso: 18-nov-2026. Todos los datos son sintéticos.
> Las cifras marcadas con **(S)** son supuestos a validar con Claro; el MVP las medirá.

## 1.1 Entendimiento del negocio

Claro atiende millones de clientes hogar y móvil por call center, chat, WhatsApp, tienda y app.
El asesor resuelve consultando **fuentes dispersas y cambiantes** (catálogo, contratos, políticas,
manuales, comunicados del NOC, regulación CRC, histórico de PQR) además de **sistemas** (CRM, facturación).

| Problema | Causa raíz | Efecto | KPI que lo mide |
|---|---|---|---|
| AHT alto | Búsqueda manual en 5–8 fuentes por interacción | Más costo por contacto, colas | AHT |
| Respuestas inconsistentes | Cada asesor interpreta el documento que encuentra; versiones viejas circulando | Errores en permanencias, tarifas, PQR | Exactitud, groundedness |
| FCR bajo / alto escalamiento | Falta de criterio en reglas complejas (ajustes > $50.000, LOS > 10 min, matriz de retención) | Re-llamadas, carga en nivel 2 | FCR, % escalamiento |
| Retención perdida | El asesor no cruza antigüedad + mora + ofertas previas + tickets a tiempo | Churn evitable | Tasa de retención |

## 1.2 Actores

| Actor | Rol en la solución |
|---|---|
| **Asesor nivel 1** (usuario principal) | Conversa con el cliente, consulta al Copiloto, confirma acciones con efecto |
| **Supervisor** | Recibe escalamientos; aprueba ajustes > $50.000 |
| **Soporte nivel 2 / Mesa de Retención** | Recibe tickets escalados y clientes de alto valor (≥ $150.000) |
| **Cliente final** | Indirecto en MVP; directo por chat en el roadmap |
| **Dueño de contenido** (Producto, Legal, NOC) | Publica/actualiza documentos → se reindexan solos |
| **Equipo IA/MLOps** | Opera prompts, modelos, evaluaciones, tableros |
| **Sistemas** | CRM (mock), Facturación (mock), repositorio documental, LLM providers |

## 1.3 Casos de uso del MVP

| ID | Caso de uso | Capacidad técnica | Golden dataset |
|---|---|---|---|
| CU-01 | Pregunta sobre planes, contratos, políticas o soporte con **cita a la fuente** | RAG híbrido + reranking | GQ-01…GQ-24 |
| CU-02 | Consulta de **ficha del cliente**: plan, facturas, saldo, tickets | Tool calling → CRM/Facturación | GQ-25 |
| CU-03 | **Retención**: detecta intención de cancelar, valida elegibilidad y sugiere RET-A/RET-B | Agente + reglas de política + modelo de churn | GQ-13…15, 26–28 |
| CU-04 | **Acción con efecto** (crear ticket, registrar oferta, ajuste) solo con confirmación del asesor | Human-in-the-loop | GQ-28 |
| CU-05 | **Escalamiento** por tema sensible (SIC, tutela, fraude, vulnerabilidad) o baja confianza | Guardrails + clasificador | GQ-29 |
| CU-06 | **Fuera de alcance** → rechazo amable | Guardrail de dominio | GQ-30 |
| CU-07 | **Resumen y clasificación de intención** al cerrar la interacción (sin PII) | LLM + clasificador ML | Transcripciones |
| CU-08 | **Actualización de fuentes**: nuevo catálogo v2 se indexa solo y la v1 queda no vigente | Pipeline por eventos | 06_actualizaciones |
| CU-09 | **Transcripción** de audios de llamadas e indexación anonimizada | Whisper + PII masking | 3 .wav |

## 1.4 Alcance del MVP

**Dentro**
- Web Angular para asesor: chat con streaming, citas, ficha del cliente, 👍/👎, escalar.
- API FastAPI + orquestador agéntico (LangGraph) con tools vía **MCP** sobre los mocks OpenAPI.
- Ingesta automática (carpeta vigilada → extracción → PII → chunking → embeddings → índice versionado).
- RAG híbrido (vector + BM25) + reranking + filtros de metadatos (vigencia, tipo de doc).
- Memoria corta en **Redis** (sesión con TTL, caché semántico, rate limiting) y memoria larga en **MongoDB**
  (resúmenes por cliente, historial de interacciones, feedback y auditoría de decisiones del agente).
- Ruteo multi-LLM por tarea/costo con fallback.
- 2 modelos ML clásicos: intención (tickets) y churn (clientes) con MLflow + drift.
- LLMOps: prompts versionados, evaluación con golden dataset como gate de CI, trazas (Langfuse).
- Automatización cognitiva con n8n: escalamientos y acciones confirmadas → tickets, notificaciones y ERP (mock).
- Fine-tuning comparativo del clasificador de intención (ver 1.8).
- Docker Compose (1 comando), CI/CD en GitHub Actions, Terraform (Azure) validado con `validate`/`test` (y `plan` si hay suscripción).
- Tablero de métricas: negocio, calidad LLM, técnica, agentes, ML.

**Fuera (roadmap)**
- Canal cliente final (WhatsApp/web) y voz en tiempo real.
- Integración real con CRM/ERP y SSO corporativo (en MVP: JWT local con roles).
- Datos de red near-real-time (se diseña el flujo de streaming, no se implementa).
- Fine-tuning productivo (se justifica en 1.8; en el MVP se ejecuta como experimento comparativo).

## 1.5 Supuestos

1. No hay nube disponible: demo **local** con Docker Compose; IaC en Terraform lista para Azure (`terraform plan`).
2. Proveedor LLM disponible: **OpenAI** (API key de pruebas). Se agrega **modelo open source local (Ollama)** para demostrar multi-LLM y fallback sin depender de otra llave.
3. El asesor ya validó la identidad del titular antes de consultar datos (Ley 1581).
4. Los documentos de las carpetas de insumo son la "fuente oficial"; si algo no está ahí → no se responde y se escala.
5. Las cifras de negocio del business case son referenciales **(S)**; el MVP deja la instrumentación para medirlas en piloto (A/B asesores con y sin Copiloto).

## 1.6 KPIs objetivo y cómo se miden

| Categoría | KPI | Meta MVP | Cómo se mide en la solución |
|---|---|---|---|
| Negocio | Reducción AHT | ≥ 20 % | Duración sesión con vs sin Copiloto (piloto A/B) |
| Negocio | FCR | +10 pp | Sesiones cerradas sin re-contacto/ticket en 7 días |
| Negocio | Escalamiento a N2 | −15 % | Tickets `escalar_a` / sesiones |
| Negocio | Retención con intención de cancelar | Medida | Ofertas RET registradas aceptadas / intenciones de cancelación |
| Calidad LLM | Groundedness | ≥ 0,85 | LLM-as-judge (Ragas faithfulness) sobre golden + muestreo prod |
| Calidad LLM | Exactitud vs golden | ≥ 80 % | % puntos_clave presentes por respuesta |
| Calidad LLM | Recall@k retriever | ≥ 0,90 | Fuente esperada en top-k |
| Calidad LLM | Respuestas sin cita / alucinación | ≤ 5 % | Validador de citas post-generación |
| Calidad LLM | Satisfacción asesor | ≥ 80 % 👍 | Feedback en UI |
| Técnica | Latencia p95 | ≤ 2 s TTFT / ≤ 8 s total | Trazas por request |
| Técnica | Disponibilidad | ≥ 99 % | Health checks + uptime |
| Técnica | Costo por conversación | < USD 0,02 **(S)** | Tokens × precio por modelo en cada traza |
| Técnica | Frescura documental | ≤ 15 min | t(indexado) − t(archivo detectado) |
| Agentes | Éxito de tareas | ≥ 90 % | Golden de herramientas (GQ-25…28) |
| Agentes | Error de tools / bucles / acción no permitida | ≤ 3 % / 0 | Contadores en trazas; límite de pasos |
| ML | F1 intención / AUC churn | ≥ 0,80 / ≥ 0,75 | MLflow |
| ML | Drift | Alertado | Evidently (PSI) vs dataset de entrenamiento |
| DevOps | Cobertura / lead time | ≥ 70 % / < 30 min | pytest-cov / duración pipeline |
| DevOps | Imagen / CVEs críticas | Slim / 0 | Trivy en CI |

## 1.7 ¿Por qué IA generativa y no otra solución?

| Alternativa | Por qué no basta |
|---|---|
| Buscador documental (keyword/intranet) | Devuelve documentos, no respuestas; el asesor sigue leyendo y combinando fuentes (no baja AHT) |
| Chatbot de reglas / árbol de decisión | Frágil ante lenguaje natural; costoso de mantener con documentos que cambian semanalmente |
| Solo ML clásico | Bueno para **clasificar y predecir** (intención, churn) pero no genera respuestas ni razona sobre políticas |
| Fine-tuning puro | El conocimiento cambia con frecuencia: reentrenar por cada catálogo no es viable y no da citas |

**Decisión:** **RAG + agente con herramientas + ML clásico** combinados.
- La IA generativa sintetiza varias fuentes, explica en lenguaje natural y **cita** → consistencia y auditabilidad.
- Las reglas críticas (elegibilidad de retención, límites de ajuste) se implementan como **lógica determinística en tools**, no se dejan al LLM.
- El ML clásico aporta señales baratas, rápidas y explicables (intención, riesgo de churn).

## 1.8 Fine-tuning: posición técnica

El PDF lo menciona. Decisión: **no** como mecanismo de conocimiento (eso es RAG). Sí tiene sentido para:
- Estilo/tono y formato de respuesta corporativo.
- Modelo pequeño especializado en clasificación de intención/resumen → bajar costo por llamada.
En el MVP: experimento real sobre el clasificador de intención (tickets deduplicados → JSONL de fine-tuning) comparando **SVM lineal vs LLM con prompt vs LLM con fine-tuning** en F1 macro, costo por 1.000 clasificaciones y latencia p95, con el mismo split agrupado sin fuga. Pasa al roadmap productivo solo si mejora F1 ≥ 3 pp frente al SVM o iguala calidad a menor costo/latencia que el LLM con prompt.

## 1.9 Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Alucinación en tarifas/permanencias | Alto (reclamos, CRC) | Respuesta solo con contexto recuperado, cita obligatoria, validador de citas, "no sé → escalar" |
| Exposición de PII (Ley 1581) | Alto (legal) | Anonimización en ingesta (Presidio), masking en logs/trazas, el LLM nunca recibe documento/teléfono/correo |
| Prompt injection (en documentos o en el chat) | Alto | Separación instrucciones/datos, guardrails de entrada, tools con allow-list y confirmación humana |
| Acciones con efecto no autorizadas | Alto | POST solo tras confirmación explícita del asesor; reglas de negocio en el tool; tope de pasos del agente |
| Documento desactualizado usado en respuesta | Medio | Versionado + metadato `vigente`; filtro obligatorio en el retriever |
| Falla/latencia del proveedor LLM | Medio | Router con fallback (OpenAI ↔ modelo local), timeouts, reintentos con backoff, degradación a "solo búsqueda" |
| Rate limits de CRM (60/min) y 503 (2 %) | Medio | Retries con backoff + `Retry-After`, circuit breaker, caché de ficha por sesión |
| Costo descontrolado | Medio | Ruteo por tarea al modelo más barato, caché semántico, límites por usuario/día |
| Degradación de calidad tras cambio de prompt/modelo | Medio | Golden dataset como gate de CI; prompts versionados; rollback de versión |
| Drift en datos de ML | Bajo/Medio | Monitoreo PSI + alerta + reentrenamiento programado |
| Calidad de datos fuente (duplicados, atípicos, faltantes) | Medio | Pipeline de limpieza documentado (ver 1.10) |

## 1.10 Hallazgos de calidad de datos (validación de insumos)

| Archivo | Hallazgo | Tratamiento |
|---|---|---|
| tickets.csv (3.816) | 20 filas duplicadas; clases desbalanceadas (soporte 1.571 vs portabilidad 279) | Deduplicar; `class_weight` / estratificación; F1 macro |
| clientes_churn.csv (3.012) | 12 IDs duplicados; 40 sin ciudad; antigüedad −5; uso datos 8.786 GB; valor_mensual 0; 863 NPS vacíos; target 15 % | Dedup; imputación/categoría "desconocido"; clipping de atípicos; indicador de NPS faltante; AUC + balanceo |
| Transcripciones | Contienen nombre y número de documento del cliente | Anonimización antes de indexar |
| CRM mock | IDs `C-xxxx` (20 clientes) distintos de `CL-xxxxx` del CSV | Datasets independientes: CRM para tools, CSV para entrenar |
| APIs | 429 a 60 req/min, 503 en 2 %, POST con efecto, ajuste > $50.000 → 403 | Mock fiel al contrato + resiliencia en el cliente |

## 1.11 Business case (referencial)

Supuestos **(S)**: 1.000 asesores · 40 interacciones/día · AHT base 6 min · costo asesor USD 6/h.

| Palanca | Cálculo | Valor anual aprox. |
|---|---|---|
| −20 % AHT | 1,2 min × 40 × 1.000 × 264 días = 211.200 h | ≈ USD 1,27 M en capacidad liberada |
| −15 % escalamiento N2 | Menos tickets a nivel 2 | A medir en piloto |
| Retención | +1 pp de retención en clientes que llaman a cancelar | A medir (alto impacto en ingresos recurrentes) |
| Costo IA | 10,56 M conversaciones × USD 0,02 | ≈ USD 0,21 M/año |

Lectura: incluso solo con la palanca de AHT el retorno es claramente positivo; el piloto valida los supuestos.

## 1.12 Glosario

### Negocio y atención al cliente

| Término | Definición |
|---|---|
| **AHT** (Average Handling Time) | Tiempo medio de atención: duración promedio de una interacción, incluyendo búsqueda de información y cierre. |
| **FCR** (First Contact Resolution) | Resolución en primer contacto: % de casos resueltos sin que el cliente tenga que volver a llamar o escribir. |
| **Escalamiento N2** | Traslado de un caso del asesor de primer nivel (N1) a soporte especializado (nivel 2), supervisor o mesa de retención. |
| **Churn** | Cancelación de servicios por parte del cliente. "Churn 90d" = canceló en los 90 días siguientes a la fecha de corte. |
| **Retención** | Acciones para evitar que un cliente con intención de cancelar se vaya (ofertas RET-A / RET-B según política). |
| **Permanencia** | Cláusula contractual que obliga a mantener el servicio un tiempo mínimo; cancelar antes genera penalidad proporcional. |
| **Convergencia** | Cliente con servicios hogar + móvil a nombre del mismo titular; recibe descuento sobre el plan móvil. |
| **Mora** | Días de atraso en el pago de la factura. Mora > 30 días inhabilita ofertas de retención. |
| **Portabilidad numérica** | Derecho del usuario a cambiar de operador conservando su número móvil; el NIP autoriza el trámite. |
| **PQR** | Peticiones, Quejas y Reclamos; deben responderse en 15 días hábiles. |
| **NPS** (Net Promoter Score) | Calificación 0–10 de qué tanto recomendaría el cliente a la empresa. |
| **CRC** | Comisión de Regulación de Comunicaciones de Colombia. |
| **SIC** | Superintendencia de Industria y Comercio; quejas ante ella son causal de escalamiento obligatorio. |
| **NOC** (Network Operations Center) | Centro de operaciones de red; emite comunicados de incidentes masivos. |
| **Alto valor** | Cliente con facturación mensual ≥ $150.000; puede transferirse a la Mesa de Retención Especializada. |
| **Piloto A/B** | Experimento con dos grupos de asesores (con y sin copiloto) para medir el impacto real atribuible a la solución. |
| **Business case** | Justificación económica: valor esperado frente a costo de la solución. |
| **MVP** (Minimum Viable Product) | Primera versión con el alcance mínimo que demuestra valor y permite medir. |

### IA y datos (conceptos generales)

| Término | Definición |
|---|---|
| **IA generativa / LLM** | Modelos de lenguaje de gran tamaño (Large Language Model) que entienden y generan texto en lenguaje natural. |
| **Copiloto** | Asistente de IA que apoya al humano en su trabajo; propone, pero la decisión final es de la persona. |
| **RAG** (Retrieval-Augmented Generation) | Técnica que primero recupera fragmentos relevantes de documentos oficiales y luego le pide al LLM responder solo con ellos, citando la fuente. |
| **Alucinación** | Respuesta del LLM que suena correcta pero no está respaldada por las fuentes. |
| **Groundedness / fidelidad** | Grado en que una respuesta está sustentada en el contexto recuperado (0 a 1). |
| **Golden dataset** | Conjunto de preguntas con respuesta esperada (30 en este caso) usado para evaluar automáticamente la calidad. |
| **Tool calling** | Capacidad del LLM de invocar funciones externas (APIs de CRM, facturación) con parámetros estructurados. |
| **Agente** | Sistema que razona en varios pasos, decide qué herramientas usar y combina resultados para cumplir una tarea. |
| **Human-in-the-loop (HITL)** | Punto del flujo donde una persona debe confirmar antes de ejecutar una acción con efecto. |
| **Guardrails** | Controles que filtran entradas y salidas del LLM: PII, prompt injection, temas fuera de alcance, citas. |
| **Fine-tuning** | Reentrenar parcialmente un modelo con ejemplos propios para ajustar estilo o especializarlo en una tarea. |
| **ML clásico** | Modelos estadísticos tradicionales (regresión logística, SVM, árboles) entrenados con datos etiquetados; rápidos y explicables. |
| **Clasificación de intención** | Determinar el motivo del contacto: soporte, facturación, consulta de planes, cancelación o portabilidad. |
| **F1 / AUC** | Métricas de modelos: F1 equilibra precisión y exhaustividad; AUC mide la capacidad de separar clientes que cancelan de los que no. |
| **Drift** | Cambio en la distribución de los datos o del comportamiento del modelo respecto al entrenamiento; obliga a reentrenar. |
| **Fuga de datos** (data leakage) | Error de validación donde el modelo ve en entrenamiento información del conjunto de prueba, inflando las métricas. |
| **PII** | Información personal identificable: nombre, documento, celular, correo. |
| **Ley 1581 de 2012** | Ley colombiana de protección de datos personales (Habeas Data). |
| **Anonimización** | Reemplazo o eliminación de PII antes de procesar o almacenar información. |
| **Prompt injection** | Ataque en el que un texto malicioso intenta cambiar las instrucciones del LLM. |
| **Token** | Unidad mínima de texto que procesa un LLM; base del costo de uso. |
