# API y agente

**Tecnología:** Python 3.12 · FastAPI · LangGraph  
**Fases del caso:** 4, 7, 8  
**Estado:** pendiente

## Responsabilidades

- Autenticación JWT por rol (asesor, supervisor, admin) y rate limit
- Grafo agéntico: guardrails → intención → planner → RAG / tools / retención → respuesta con citas
- Límite de pasos, detección de bucles y pausa human-in-the-loop
- Memoria corta (Redis) y larga (MongoDB); prompts versionados en `prompts/`

## Pruebas

pytest con mocks de LLM y de tools; evaluación con el golden dataset
