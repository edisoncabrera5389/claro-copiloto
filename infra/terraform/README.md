# Terraform · Azure (dev / prod)

Implementa la columna *Azure* del SAD 2.12 con las **mismas imágenes** de docker compose: solo cambian la configuración
y los servicios administrados. Se valida y prueba **sin credenciales ni costo** (Docker, `terraform test` con
proveedores simulados); el despliegue real es un workflow manual con OIDC.

```
infra/terraform/
├── plataforma/          módulo con un archivo por preocupación
│   ├── base.tf          grupo de recursos, Log Analytics, App Insights, Prometheus + Grafana (prod), identidad, ACR
│   ├── red.tf           VNet, subred delegada a Container Apps, NSG, private endpoints + DNS privado (prod)
│   ├── datos.tf         Storage (fuentes versionadas) + Event Grid → cola, Cosmos DB (Mongo), Azure Managed Redis
│   ├── ia.tf            Azure OpenAI con los despliegues economico / alto / embedding (alias de LiteLLM)
│   ├── secretos.tf      Key Vault (RBAC) y secretos generados o tomados de los recursos (nunca en variables)
│   ├── apps.tf          Container Apps (KEDA, revisiones para canary) y Job de ingesta event-driven
│   ├── diagnostico.tf   auditoría de Key Vault y operaciones de Storage a Log Analytics
│   ├── finops.tf        presupuesto mensual con alertas 80 % / 100 %
│   └── tests/           terraform test con mock_provider (5 escenarios)
└── entornos/{dev,prod}  raíces delgadas: backend remoto, proveedor con OIDC y valores del ambiente
```

## Arquitectura

| Componente (compose) | Azure | dev | prod |
|---|---|---|---|
| frontend, api, mcp-server, ml-service, litellm | Container Apps (KEDA por solicitudes concurrentes) | 1–3 réplicas | 2–30 réplicas, **revisiones múltiples (canary)**, zonas |
| ingesta watcher + worker | **Blob + Event Grid → Storage Queue → Container Apps Job** (escala desde 0; KEDA lee la cola con la identidad) | ✓ | ✓ |
| Qdrant | Container App + Azure Files | ✓ | a escala: Qdrant Cloud o AI Search |
| MongoDB | Cosmos DB API Mongo 7.0 | serverless | autoscale 4.000 RU, backup continuo, zonas |
| Redis 8 | Azure Managed Redis | Balanced B0 | Balanced B1 con alta disponibilidad |
| OpenAI | Azure OpenAI (gpt-4.1-mini, gpt-4.1, text-embedding-3-small) | 50/20/50 K TPM | 300/100/150 K TPM |
| Prometheus + Grafana | Azure Monitor (Prometheus) + Managed Grafana | — | ✓ |
| Phoenix, MLflow, n8n | Container Apps internas (+ Azure Files) | ✓ | ✓ |
| Mocks CRM/Facturación/ERP | Container Apps | ✓ | — (MCP → sistemas reales) |
| `.env` | **Key Vault + identidad administrada** | ✓ | ✓ |
| Red | VNet + NSG; solo el frontend tiene ingress externo | servicios con acceso público | **todo por private endpoint** (8) |

**Decisiones**
- **Secretos:** los internos (JWT, firma de confirmaciones, LiteLLM…) se generan con `random_password`. Los de servicios (OpenAI, Cosmos, Redis) se toman de los propios recursos. Todos van a Key Vault y las apps los leen por referencia con su identidad administrada. Ningún secreto pasa por variables ni por el repo. Como el estado sí los contiene, el backend remoto usa Entra ID, cifrado y acceso privado.
- **Canary:** las apps con revisiones múltiples ignoran `traffic_weight` en Terraform (`lifecycle`). El pesaje 10 % → 100 % lo hace el pipeline de despliegue, así Terraform no revierte un canary en curso.
- **Frontend:** Nginx llega a la API con `API_UPSTREAM=api:80` (ingress interno por nombre) y `Host: api`, porque el Envoy de Container Apps enruta por `Host`. En compose sigue siendo `api:8000`.
- **`prevent_destroy`** protege Cosmos (auditoría de 5 años), Key Vault y las fuentes. Redis, la cola y los volúmenes reconstruibles quedan excluidos con el motivo documentado.
- **FinOps:** presupuesto de US$ 300/mes en dev y US$ 3.000/mes en prod (topes de referencia; validar precios vigentes), etiquetas de costo, tope diario de logs en dev y Cosmos serverless.

## Validar sin Azure (todo en Docker; Terraform no hace falta instalado)

En la máquina de demo, en una línea (~45 s, salida con resumen y código de salida 1 si algo falla):

```powershell
./scripts/terraform.ps1            # todo: formato, validate de plataforma/dev/prod, pruebas, tflint y checkov
./scripts/terraform.ps1 validar    # fmt + validate
./scripts/terraform.ps1 probar     # terraform test (Azure simulado)
./scripts/terraform.ps1 seguridad  # tflint + checkov
```

Los comandos equivalentes, uno por uno:

```powershell
cd infra/terraform
$TF = "docker run --rm -v ${PWD}:/tf -v tf-cache:/cache -e TF_PLUGIN_CACHE_DIR=/cache"
iex "$TF -w /tf hashicorp/terraform:1.17.2 fmt -recursive -check"
foreach ($r in "plataforma","entornos/dev","entornos/prod") {
  iex "$TF -w /tf/$r hashicorp/terraform:1.17.2 init -backend=false"
  iex "$TF -w /tf/$r hashicorp/terraform:1.17.2 validate"
}
iex "$TF -w /tf/plataforma hashicorp/terraform:1.17.2 test"     # 5 escenarios con proveedores simulados
docker run --rm -v ${PWD}:/data -w /data ghcr.io/terraform-linters/tflint:v0.66.0 --init
docker run --rm -v ${PWD}:/data -w /data ghcr.io/terraform-linters/tflint:v0.66.0 --recursive
docker run --rm -v ${PWD}:/tf -w /tf bridgecrew/checkov:3.4.6 --config-file /tf/.checkov.yaml
```

El CI corre lo mismo en el job **Terraform (Azure)**.

| Verificación | Resultado |
|---|---|
| `terraform validate` (plataforma, dev, prod) contra azurerm 5.14 | ✅ sin avisos de deprecación |
| `terraform test` (mock_provider) | ✅ 5/5. Solo el frontend es público; secretos solo por Key Vault; dev serverless sin private endpoints; prod con 8 private endpoints, purga protegida, backup continuo, ZRS, canary y ≥ 2 réplicas; validaciones de variables. Una prueba de mutación (API pública) la detecta |
| tflint (ruleset azurerm 0.33) | ✅ 0 avisos |
| checkov 3.4.6 | ✅ 33 aprobadas, 0 fallidas. 37 excepciones con su razón junto al recurso: acceso público solo en dev, CMK en la hoja de ruta, Azure Files exige clave de cuenta, escaneo de imágenes con Trivy en el CI |

**Hallazgos de la validación:**
- azurerm 5 cambió el esquema: el enlace de DNS privado usa `private_dns_zone_id`, Grafana exige la versión 12 o 13 y en Storage se reemplaza `public_network_access_enabled`.
- La regla de escala del Job acepta `identity_id`, así que KEDA lee la cola sin clave.
- checkov propuso mejoras reales que se aplicaron: NSG en la subred de apps, solo HTTPS desde Internet, prevención de fuga de datos e identidad en OpenAI, y diagnóstico de Key Vault y Storage.

## Desplegar en Azure (manual)

Workflow **Azure (Terraform)** (`.github/workflows/azure.yml`): `plan` o `apply` por ambiente, con OIDC (sin
secretos guardados). Usa las imágenes que el CI publicó en GHCR para el SHA elegido. Requisitos de una sola vez (en el
encabezado del workflow): app de Entra ID con credencial federada, storage del estado, variables del repo y
environments `azure-dev` / `azure-prod` (con revisores en prod).

## Siguientes pasos

- Worker de ingesta: adaptador de **Storage Queue** (hoy consume Redis Streams, el mecanismo local); la infraestructura de eventos ya está.
- OpenAI y Cosmos con **Entra ID** en lugar de claves; **CMK** donde el cumplimiento lo exija.
- Recolección de métricas de las apps hacia Azure Monitor (Prometheus administrado) y exportador OTel → Application Insights.
- n8n: importar los flujos de `infra/n8n/flujos` al arrancar en ACA (imagen propia o Job de inicialización).
