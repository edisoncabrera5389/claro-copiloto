# Pruebas de la plataforma con proveedores simulados (sin credenciales ni costo):
#   terraform test   (desde infra/terraform/plataforma)
# Verifican las reglas de arquitectura y seguridad del SAD, no solo que el código "compile".

mock_provider "azurerm" {
  # IDs con formato de Azure: varios argumentos (scope, *_id) validan el formato incluso con proveedor simulado.
  mock_resource "azurerm_resource_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba"
    }
  }
  mock_resource "azurerm_key_vault" {
    defaults = {
      id        = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.KeyVault/vaults/kvprueba"
      vault_uri = "https://kvprueba.vault.azure.net/"
    }
  }
  mock_resource "azurerm_key_vault_secret" {
    defaults = {
      id             = "https://kvprueba.vault.azure.net/secrets/secreto/0123456789abcdef0123456789abcdef"
      versionless_id = "https://kvprueba.vault.azure.net/secrets/secreto"
      resource_id    = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.KeyVault/vaults/kvprueba/secrets/secreto/versions/0123456789abcdef0123456789abcdef"
    }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-prueba"
      principal_id = "00000000-0000-0000-0000-000000000004"
      client_id    = "00000000-0000-0000-0000-000000000005"
    }
  }
  mock_resource "azurerm_container_registry" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.ContainerRegistry/registries/acrprueba"
      login_server = "acrprueba.azurecr.io"
    }
  }
  mock_resource "azurerm_storage_account" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.Storage/storageAccounts/stprueba"
    }
  }
  mock_resource "azurerm_storage_container" {
    defaults = {
      id                  = "https://stprueba.blob.core.windows.net/fuentes"
      resource_manager_id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.Storage/storageAccounts/stprueba/blobServices/default/containers/fuentes"
    }
  }
  mock_resource "azurerm_storage_queue" {
    defaults = {
      id                  = "https://stprueba.queue.core.windows.net/ingesta-eventos"
      resource_manager_id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.Storage/storageAccounts/stprueba/queueServices/default/queues/ingesta-eventos"
    }
  }
  mock_resource "azurerm_storage_share" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.Storage/storageAccounts/stprueba/fileServices/default/shares/volumen"
    }
  }
  mock_resource "azurerm_cosmosdb_account" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.DocumentDB/databaseAccounts/cosmosprueba"
    }
  }
  mock_resource "azurerm_cognitive_account" {
    defaults = {
      id       = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.CognitiveServices/accounts/oaiprueba"
      endpoint = "https://oaiprueba.openai.azure.com/"
    }
  }
  mock_resource "azurerm_managed_redis" {
    defaults = {
      id       = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.Cache/redisEnterprise/redisprueba"
      hostname = "redisprueba.eastus2.redis.azure.net"
    }
  }
  mock_resource "azurerm_log_analytics_workspace" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.OperationalInsights/workspaces/logprueba"
    }
  }
  mock_resource "azurerm_application_insights" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.Insights/components/appiprueba"
    }
  }
  mock_resource "azurerm_monitor_workspace" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.Monitor/accounts/amwprueba"
    }
  }
  mock_resource "azurerm_virtual_network" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.Network/virtualNetworks/vnetprueba"
    }
  }
  mock_resource "azurerm_subnet" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.Network/virtualNetworks/vnetprueba/subnets/snetprueba"
    }
  }
  mock_resource "azurerm_network_security_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.Network/networkSecurityGroups/nsgprueba"
    }
  }
  mock_resource "azurerm_private_dns_zone" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.Network/privateDnsZones/privatelink.prueba.net"
    }
  }
  mock_resource "azurerm_container_app_environment" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.App/managedEnvironments/caeprueba"
    }
  }
  mock_resource "azurerm_container_app_environment_storage" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.App/managedEnvironments/caeprueba/storages/volumen"
    }
  }
  mock_resource "azurerm_eventgrid_system_topic" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-prueba/providers/Microsoft.EventGrid/systemTopics/evgtprueba"
    }
  }

  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "00000000-0000-0000-0000-000000000001"
      object_id       = "00000000-0000-0000-0000-000000000002"
      subscription_id = "00000000-0000-0000-0000-000000000003"
    }
  }
}

mock_provider "random" {}

variables {
  imagen = { tag = "c920723" }
  presupuesto = {
    monto_mensual = 300
    correos       = ["finops@ejemplo.com"]
    inicio        = "2026-12-01T00:00:00Z"
  }
}

run "dev_costo_minimo_y_publico_restringido" {
  command = apply

  variables {
    entorno         = "dev"
    privado         = false
    desplegar_mocks = true
    escala          = { minimo_api = 1, maximo_api = 3, concurrencia = 20, zonas = false }
  }

  assert {
    condition     = alltrue([for k, a in azurerm_container_app.app : a.ingress[0].external_enabled == (k == "frontend")])
    error_message = "Solo el frontend puede tener ingress externo; API, MCP, LiteLLM, datos y RPA son internos."
  }
  assert {
    condition     = alltrue([for k in ["crm-mock", "facturacion-mock", "erp-mock"] : contains(keys(azurerm_container_app.app), k)])
    error_message = "En dev se despliegan los mocks de CRM, Facturación y ERP."
  }
  assert {
    condition     = length(azurerm_private_endpoint.pe) == 0 && azurerm_key_vault.kv.public_network_access_enabled
    error_message = "Dev no usa private endpoints (costo); prod sí."
  }
  assert {
    condition     = contains([for c in azurerm_cosmosdb_account.cosmos.capabilities : c.name], "EnableServerless")
    error_message = "Cosmos en dev debe ser serverless (paga por uso)."
  }
  assert {
    condition     = azurerm_container_app.app["api"].revision_mode == "Single" && length(azurerm_dashboard_grafana.grafana) == 0
    error_message = "Dev: una sola revisión y sin Grafana administrado."
  }
  assert {
    condition     = azurerm_log_analytics_workspace.logs.daily_quota_gb == 1
    error_message = "Dev limita la ingesta diaria de logs (FinOps)."
  }
  assert {
    condition     = endswith(azurerm_container_app.app["api"].template[0].container[0].image, "/api:c920723")
    error_message = "Las imágenes propias se despliegan por el SHA del commit."
  }
  assert {
    condition     = one([for e in azurerm_container_app.app["frontend"].template[0].container[0].env : e.value if e.name == "API_UPSTREAM"]) == "api:80"
    error_message = "El frontend llega a la API por el ingress interno de Container Apps (api:80)."
  }
}

run "seguridad_comun" {
  command = apply

  variables {
    entorno         = "dev"
    privado         = false
    desplegar_mocks = true
    escala          = { minimo_api = 1, maximo_api = 3, concurrencia = 20, zonas = false }
  }

  assert {
    condition = alltrue([for e in azurerm_container_app.app["api"].template[0].container[0].env :
    e.secret_name != null && e.value == null if contains(["JWT_SECRET", "API_DEMO_PASSWORD", "LITELLM_MASTER_KEY", "MCP_CONFIRMACION_SECRET", "API_REDIS_URL", "API_MONGO_URL"], e.name)])
    error_message = "Los secretos de la API llegan como referencias a Key Vault, nunca como texto plano."
  }
  assert {
    condition     = alltrue([for k, a in azurerm_container_app.app : alltrue([for s in a.secret : s.key_vault_secret_id != null && s.identity != null])])
    error_message = "Todo secreto de una app se lee de Key Vault con la identidad administrada."
  }
  assert {
    condition     = !azurerm_container_registry.acr.admin_enabled && azurerm_key_vault.kv.rbac_authorization_enabled
    error_message = "ACR sin usuario admin y Key Vault con RBAC (sin access policies)."
  }
  assert {
    condition     = azurerm_storage_account.datos.min_tls_version == "TLS1_2" && !azurerm_storage_account.datos.allow_nested_items_to_be_public
    error_message = "Storage: TLS 1.2 y sin blobs públicos."
  }
  assert {
    condition     = azurerm_storage_container.fuentes.container_access_type == "private" && azurerm_storage_account.datos.blob_properties[0].versioning_enabled
    error_message = "Fuentes privadas y versionadas (linaje de documentos)."
  }
  assert {
    condition     = alltrue([for n in ["proyecto", "entorno", "gestionado"] : contains(keys(azurerm_resource_group.rg.tags), n)])
    error_message = "Etiquetas mínimas de costo y gobierno en todos los recursos."
  }
  assert {
    condition     = toset([for n in azurerm_consumption_budget_resource_group.mensual.notification : n.threshold]) == toset([80, 100])
    error_message = "El presupuesto avisa al 80 % real y al 100 % pronosticado."
  }
  assert {
    condition     = azurerm_container_app_job.ingesta.event_trigger_config[0].scale[0].min_executions == 0 && azurerm_container_app_job.ingesta.event_trigger_config[0].scale[0].rules[0].identity_id != null
    error_message = "La ingesta escala desde 0 por eventos de la cola y KEDA la lee con identidad (sin clave)."
  }
  assert {
    condition     = toset(azurerm_eventgrid_system_topic_event_subscription.ingesta.included_event_types) == toset(["Microsoft.Storage.BlobCreated", "Microsoft.Storage.BlobDeleted"])
    error_message = "Frescura: altas y bajas de documentos disparan la ingesta."
  }
}

run "prod_privado_y_redundante" {
  command = apply

  variables {
    entorno         = "prod"
    privado         = true
    desplegar_mocks = false
    sistemas        = { crm = "https://crm.interno/v1", facturacion = "https://facturacion.interno/v1" }
    escala          = { minimo_api = 2, maximo_api = 30, concurrencia = 50, zonas = true }
  }

  assert {
    condition     = length(azurerm_private_endpoint.pe) == 8
    error_message = "Prod: private endpoints para Key Vault, Cosmos, Redis, Blob, Queue, Files, OpenAI y ACR."
  }
  assert {
    condition = (!azurerm_key_vault.kv.public_network_access_enabled && !azurerm_cosmosdb_account.cosmos.public_network_access_enabled
      && azurerm_storage_account.datos.public_network_access == "Disabled" && !azurerm_cognitive_account.openai.public_network_access_enabled
    && azurerm_managed_redis.redis.public_network_access == "Disabled")
    error_message = "Prod: ningún servicio de datos o IA con acceso público."
  }
  assert {
    condition     = azurerm_key_vault.kv.purge_protection_enabled && azurerm_key_vault.kv.soft_delete_retention_days == 90
    error_message = "Prod: Key Vault con protección de purga y 90 días de borrado lógico."
  }
  assert {
    condition     = azurerm_cosmosdb_account.cosmos.backup[0].type == "Continuous" && azurerm_storage_account.datos.account_replication_type == "ZRS"
    error_message = "Prod: backup continuo de Cosmos y almacenamiento redundante por zona."
  }
  assert {
    condition     = azurerm_container_app.app["api"].revision_mode == "Multiple" && azurerm_container_app.app["api"].template[0].min_replicas >= 2
    error_message = "Prod: revisiones múltiples (canary) y al menos 2 réplicas de la API."
  }
  assert {
    condition     = azurerm_container_app_environment.aca.zone_redundancy_enabled && length(azurerm_dashboard_grafana.grafana) == 1
    error_message = "Prod: entorno redundante por zonas y Grafana administrado."
  }
  assert {
    condition     = !anytrue([for k in keys(azurerm_container_app.app) : endswith(k, "-mock")])
    error_message = "Prod no despliega mocks: el MCP apunta a los sistemas reales."
  }
  assert {
    condition     = one([for e in azurerm_container_app.app["mcp-server"].template[0].container[0].env : e.value if e.name == "MCP_CRM_URL"]) == "https://crm.interno/v1"
    error_message = "El MCP usa la URL del CRM real en prod."
  }
}

run "entorno_invalido" {
  command = plan
  variables {
    entorno = "qa"
    privado = false
    escala  = { minimo_api = 1, maximo_api = 3, concurrencia = 20, zonas = false }
  }
  expect_failures = [var.entorno]
}

run "presupuesto_debe_iniciar_el_primer_dia_del_mes" {
  command = plan
  variables {
    entorno     = "dev"
    privado     = false
    escala      = { minimo_api = 1, maximo_api = 3, concurrencia = 20, zonas = false }
    presupuesto = { monto_mensual = 300, correos = ["finops@ejemplo.com"], inicio = "2026-12-15T00:00:00Z" }
  }
  expect_failures = [var.presupuesto]
}
