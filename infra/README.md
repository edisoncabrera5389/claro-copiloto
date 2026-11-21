# Infraestructura

**Tecnología:** Terraform · LiteLLM · Prometheus · Grafana · n8n  
**Fases del caso:** 10, 11, 13  
**Estado:** pendiente

## Responsabilidades

- `terraform/`: módulos Azure (Container Apps, Key Vault, Storage, Redis, Cosmos DB, ACR, monitoreo) y ambientes dev/prod
- `litellm/`: modelos, ruteo por tarea, fallback y presupuestos
- `observability/`: configuración de Prometheus, tableros y alertas de Grafana
- `n8n/`: flujos exportados de automatización (escalamiento, tickets, ERP)

## Pruebas

`terraform validate`, `terraform test` con mocks, tflint y checkov
