# Control del documento

| Campo | Valor |
|---|---|
| Documento | Documento de Arquitectura de Solución (SAD) · Claro Copiloto |
| Versión | 1.0 |
| Fecha | 21 de noviembre de 2026 |
| Autor | Edison Cabrera · candidato a Líder Técnico AI Senior |
| Estado | Propuesta para sustentación |
| Clasificación | Prueba técnica · todos los datos son sintéticos |
| Fecha de referencia del caso | 18 de noviembre de 2026 |

**Historial de versiones**

| Versión | Fecha | Cambio |
|---|---|---|
| 0.1 | 21-nov-2026 | Planteamiento del problema y validación de insumos |
| 0.2 | 21-nov-2026 | Arquitectura, decisiones y comparativa de modelos de ML |
| 1.0 | 21-nov-2026 | Gestión del proyecto, glosario y consolidación para entrega |

**Documentos relacionados**

| Documento | Descripción |
|---|---|
| `docs/presentacion/Claro_Copiloto_Arquitectura.pptx` | Presentación de la propuesta (entregable principal) |
| Repositorio Git del proyecto | Código, IaC, pipelines y la fuente Markdown de este documento (`docs/`) |
| Prueba_LT_IA_Senior_v2.pdf | Enunciado del caso de negocio |

# Resumen ejecutivo

**Problema.** Los asesores de Claro consultan entre 5 y 8 fuentes dispersas y cambiantes (catálogo, contratos, políticas, manuales, comunicados del NOC) además de CRM y facturación. El resultado: tiempo medio de atención (AHT) alto, respuestas inconsistentes, baja resolución en primer contacto (FCR) y oportunidades de retención perdidas.

**Solución.** *Claro Copiloto* es un asistente de IA generativa para el asesor que:

- responde en lenguaje natural **citando la fuente y la versión** del documento (RAG híbrido con control de alucinaciones);
- consulta la **ficha del cliente** en CRM y facturación mediante herramientas expuestas por **MCP**;
- **clasifica la intención** y **sugiere la oferta de retención** aplicando la política en código determinístico, apoyado por un modelo de riesgo de churn;
- **escala a un humano** ante temas sensibles o baja confianza, y **ejecuta acciones con efecto solo con confirmación** del asesor.

**Arquitectura.** Cinco capas desacopladas (experiencia, aplicación, datos y memoria, ingesta y streaming, observabilidad) sobre contenedores. Agente en LangGraph, ruteo multi-LLM con fallback (LiteLLM: OpenAI + modelos open source locales), Qdrant para búsqueda híbrida, Redis para memoria corta y MongoDB para memoria larga y auditoría, ingesta por eventos con anonimización de PII, MLflow para los modelos clásicos y OpenTelemetry/Phoenix/Grafana para trazas y tableros. La misma arquitectura corre en Docker Compose y está definida en Terraform para Azure.

**Calidad y operación.** El golden dataset de 30 preguntas es un *gate* del pipeline CI/CD: ningún cambio de prompt, modelo o documento llega a producción si la calidad baja. Cada respuesta queda trazada con fuentes, modelo, versión de prompt, tokens, costo y latencia.

**Valor esperado (referencial, a validar en piloto).**

| Meta MVP | Valor |
|---|---|
| Reducción de AHT | ≥ 20 % |
| FCR | +10 pp |
| Groundedness de respuestas | ≥ 0,85 |
| Costo por conversación | < US$0,02 |
| Capacidad liberada estimada | ≈ US$1,27 M/año frente a ≈ US$0,21 M/año de costo de IA |

**Hallazgos clave de la validación.** Los insumos traen duplicados, atípicos, nulos y PII en transcripciones; los tickets tienen solo 164 descripciones únicas (riesgo de fuga en la validación de ML) y ruido de etiquetas. Con validación honesta, el clasificador de intención alcanza F1 macro 0,92 (SVM lineal) y el modelo de churn AUC 0,70, bajo la meta de 0,75, por lo que se usa como señal de priorización y no como decisión automática.

**Plan.** MVP en 4 semanas con un equipo de 7 personas, piloto A/B con 200 asesores durante 8 semanas y escalamiento posterior a canales de cliente final, datos de red en tiempo real, multipaís y voz (capítulo 3).
