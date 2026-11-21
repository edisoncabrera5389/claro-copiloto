# Infraestructura

**Tecnología:** Terraform · LiteLLM · Prometheus · Grafana · n8n  
**Fases del caso:** 10, 11, 13  
**Estado:** pendiente

## Responsabilidades

- `terraform/`: módulos Azure (Container Apps, Key Vault, Storage, Redis, Cosmos DB, ACR, monitoreo) y ambientes dev/prod
- `litellm/`: ✅ [config.yaml](litellm/config.yaml) del proxy LiteLLM 1.110.2 (servicio `litellm`, puerto 4000): alias `economico` (gpt-4.1-mini), `alto` (gpt-4.1), `embedding` (text-embedding-3-small) y `local` (Ollama llama3.2:3b, perfil opcional `llm-local`); fallback alto → economico → local, reintentos, enfriamiento por fallas y sin registro de mensajes. Cambiar de modelo o proveedor = editar este archivo
- `observability/`: configuración de Prometheus, tableros y alertas de Grafana
- `n8n/`: flujos exportados de automatización (escalamiento, tickets, ERP)

## Pruebas

`terraform validate`, `terraform test` con mocks, tflint y checkov
