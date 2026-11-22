# Cómputo (SAD 2.12): Azure Container Apps con KEDA, revisiones para canary y Job event-driven de ingesta.
# Mismas imágenes que docker compose; solo cambian la configuración y los servicios administrados.

locals {
  registro_acr = azurerm_container_registry.acr.login_server
  registro     = coalesce(var.imagen.registro, local.registro_acr)
  propia       = { for n in ["api", "frontend", "mcp-server", "ml-service", "mocks", "ingesta"] : n => "${local.registro}/${n}:${var.imagen.tag}" }
  min_api      = var.escala.minimo_api

  # LiteLLM en Azure: los alias de siempre apuntan a los despliegues de Azure OpenAI (mismos modelos).
  litellm_config = yamlencode({
    model_list = [for alias, m in var.modelos : {
      model_name = alias
      litellm_params = {
        model       = "azure/${alias}"
        api_base    = "os.environ/AZURE_API_BASE"
        api_key     = "os.environ/AZURE_API_KEY"
        api_version = "2024-10-21"
      }
    }]
    router_settings  = { fallbacks = [{ alto = ["economico"] }], num_retries = 2, allowed_fails = 3, cooldown_time = 30 }
    litellm_settings = { drop_params = true, request_timeout = 60, turn_off_message_logging = true }
    general_settings = { master_key = "os.environ/LITELLM_MASTER_KEY" }
  })

  crm_url         = var.desplegar_mocks ? "http://crm-mock/v1" : var.sistemas.crm
  facturacion_url = var.desplegar_mocks ? "http://facturacion-mock/v1" : var.sistemas.facturacion

  # Definición de cada app: imagen, ingress (null = sin ingress), recursos, réplicas, variables y secretos de Key Vault.
  apps = merge({
    frontend = {
      imagen   = local.propia["frontend"], puerto = 8080, externo = true, cpu = 0.25, memoria = "0.5Gi"
      min      = local.min_api, max = var.escala.maximo_api, sonda = "/salud", multiple = local.prod
      env      = { API_UPSTREAM = "api:80" }
      secretos = {}
      volumen  = null, args = null
    }
    api = {
      imagen = local.propia["api"], puerto = 8000, externo = false, cpu = 1, memoria = "2Gi"
      min    = local.min_api, max = var.escala.maximo_api, sonda = "/health/vivo", multiple = local.prod
      env = {
        API_LLM_BASE_URL  = "http://litellm/v1"
        API_QDRANT_URL    = "http://qdrant:80"
        API_MCP_URL       = "http://mcp-server/mcp"
        API_ML_URL        = "http://ml-service"
        API_N8N_URL       = "http://n8n/webhook"
        API_OTEL_ENDPOINT = "http://phoenix"
      }
      secretos = {
        JWT_SECRET              = "jwt-secret"
        API_DEMO_PASSWORD       = "demo-password"
        LITELLM_MASTER_KEY      = "litellm-master-key"
        MCP_CONFIRMACION_SECRET = "confirmacion-secret"
        API_REDIS_URL           = "redis-url"
        API_MONGO_URL           = "mongo-url"
      }
      volumen = null, args = null
    }
    mcp-server = {
      imagen   = local.propia["mcp-server"], puerto = 8090, externo = false, cpu = 0.5, memoria = "1Gi"
      min      = 1, max = 5, sonda = "/health", multiple = false
      env      = { MCP_CRM_URL = local.crm_url, MCP_FACTURACION_URL = local.facturacion_url }
      secretos = { MCP_MOCKS_API_KEY = "mocks-api-key", MCP_CONFIRMACION_SECRET = "confirmacion-secret" }
      volumen  = null, args = null
    }
    ml-service = {
      imagen   = local.propia["ml-service"], puerto = 8001, externo = false, cpu = 0.5, memoria = "1Gi"
      min      = 1, max = 5, sonda = "/health/vivo", multiple = false
      env      = { ML_MLFLOW_TRACKING_URI = "http://mlflow" }
      secretos = { ML_MONGO_URL = "mongo-url" }
      volumen  = null, args = null
    }
    litellm = {
      imagen   = "ghcr.io/berriai/litellm@sha256:ef798594ca3db8d81bad2e1439f536f49b71fe095ee9f20416f5e149b4e22035"
      puerto   = 4000, externo = false, cpu = 1, memoria = "2Gi"
      min      = 1, max = 5, sonda = "/health/liveliness", multiple = false
      env      = {}
      secretos = { LITELLM_MASTER_KEY = "litellm-master-key", AZURE_API_KEY = "openai-api-key", AZURE_API_BASE = "openai-endpoint" }
      volumen  = { nombre = "config", ruta = "/app/config", tipo = "Secret" }
      args     = ["--config", "/app/config/litellm-config", "--port", "4000"]
    }
    qdrant = {
      # Dev/demo: Qdrant en ACA con Azure Files. Prod a escala: Qdrant Cloud o Azure AI Search (SAD 2.5).
      imagen   = "qdrant/qdrant:v1.20.0", puerto = 6333, externo = false, cpu = 1, memoria = "2Gi"
      min      = 1, max = 1, sonda = "/healthz", multiple = false
      env      = { QDRANT__TELEMETRY_DISABLED = "true" }
      secretos = {}
      volumen  = { nombre = "qdrant", ruta = "/qdrant/storage", tipo = "AzureFile" }
      args     = null
    }
    mlflow = {
      imagen   = "ghcr.io/mlflow/mlflow:v3.18.0", puerto = 5000, externo = false, cpu = 0.5, memoria = "1Gi"
      min      = 1, max = 1, sonda = "/health", multiple = false
      env      = { MLFLOW_SERVER_ENABLE_JOB_EXECUTION = "false" }
      secretos = {}
      volumen  = { nombre = "mlflow", ruta = "/mlflow", tipo = "AzureFile" }
      args = ["mlflow", "server", "--host", "0.0.0.0", "--port", "5000", "--workers", "1",
        "--backend-store-uri", "sqlite:////mlflow/mlflow.db", "--artifacts-destination", "/mlflow/artifacts",
      "--serve-artifacts", "--allowed-hosts", "mlflow,mlflow:5000,mlflow:80"]
    }
    phoenix = {
      imagen   = "arizephoenix/phoenix:version-22.0.1", puerto = 6006, externo = false, cpu = 0.5, memoria = "1Gi"
      min      = 1, max = 1, sonda = "/healthz", multiple = false
      env      = { PHOENIX_TELEMETRY_ENABLED = "false", PHOENIX_ENABLE_AUTH = "false" } # solo ingress interno
      secretos = {}
      volumen  = null, args = null
    }
    n8n = {
      imagen = "n8nio/n8n:2.49.3", puerto = 5678, externo = false, cpu = 0.5, memoria = "1Gi"
      min    = 1, max = 1, sonda = "/healthz", multiple = false
      env = { N8N_BLOCK_ENV_ACCESS_IN_NODE = "false", N8N_METRICS = "true", N8N_DIAGNOSTICS_ENABLED = "false",
      GENERIC_TIMEZONE = "America/Bogota", NODE_OPTIONS = "--max-old-space-size=768" }
      secretos = { N8N_ENCRYPTION_KEY = "n8n-encryption-key", MOCKS_API_KEY = "mocks-api-key" }
      volumen  = { nombre = "n8n", ruta = "/home/node/.n8n", tipo = "AzureFile" }
      args     = null
    }
    }, var.desplegar_mocks ? { for s in ["crm", "facturacion", "erp"] : "${s}-mock" => {
      imagen   = local.propia["mocks"], puerto = { crm = 8081, facturacion = 8082, erp = 8083 }[s], externo = false
      cpu      = 0.25, memoria = "0.5Gi", min = 1, max = 1, sonda = "/health", multiple = false
      env      = { MOCKS_SERVICIO = s, MOCKS_FECHA_REFERENCIA = "2026-11-18" }
      secretos = { MOCKS_API_KEY = "mocks-api-key" }
      volumen  = { nombre = "mocks", ruta = "/data", tipo = "AzureFile" }
      args     = null
  } } : {})

  volumenes_acs = toset(concat(["qdrant", "mlflow", "n8n"], var.desplegar_mocks ? ["mocks"] : []))
}

resource "azurerm_container_app_environment" "aca" {
  name                               = "cae-${local.nombre}"
  location                           = azurerm_resource_group.rg.location
  resource_group_name                = azurerm_resource_group.rg.name
  log_analytics_workspace_id         = azurerm_log_analytics_workspace.logs.id
  infrastructure_subnet_id           = azurerm_subnet.apps.id
  infrastructure_resource_group_name = "rg-${local.nombre}-aca-infra"
  internal_load_balancer_enabled     = false # el frontend es público; el resto, ingress interno
  zone_redundancy_enabled            = var.escala.zonas
  tags                               = local.etiquetas

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}

# tflint-ignore: azurerm_resources_missing_prevent_destroy # datos sintéticos de la prueba (se vuelven a subir)
resource "azurerm_storage_share" "mocks" {
  count              = var.desplegar_mocks ? 1 : 0
  name               = "mocks" # datos sintéticos de la prueba: se suben aparte (no están en el repo)
  storage_account_id = azurerm_storage_account.datos.id
  quota              = 1
}

resource "azurerm_container_app_environment_storage" "volumen" {
  for_each                     = local.volumenes_acs
  name                         = each.key
  container_app_environment_id = azurerm_container_app_environment.aca.id
  account_name                 = azurerm_storage_account.datos.name
  share_name                   = each.key == "mocks" ? azurerm_storage_share.mocks[0].name : azurerm_storage_share.volumen[each.key].name
  access_key                   = azurerm_storage_account.datos.primary_access_key
  access_mode                  = "ReadWrite"
}

resource "azurerm_key_vault_secret" "litellm_config" {
  name            = "litellm-config"
  value           = local.litellm_config
  key_vault_id    = azurerm_key_vault.kv.id
  content_type    = "application/yaml"
  expiration_date = "2027-12-31T00:00:00Z"
  depends_on      = [azurerm_role_assignment.kv_despliegue]
}

resource "azurerm_container_app" "app" {
  for_each                     = local.apps
  name                         = each.key # el nombre es el DNS interno: http://api, http://litellm, ...
  container_app_environment_id = azurerm_container_app_environment.aca.id
  resource_group_name          = azurerm_resource_group.rg.name
  revision_mode                = each.value.multiple ? "Multiple" : "Single" # Multiple: canary 10 % → 100 %
  workload_profile_name        = "Consumption"
  tags                         = local.etiquetas

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  dynamic "registry" {
    for_each = startswith(each.value.imagen, local.registro_acr) ? [1] : []
    content {
      server   = local.registro_acr
      identity = azurerm_user_assigned_identity.apps.id
    }
  }

  # Secretos referenciados en Key Vault (la app los lee con su identidad; nunca en texto plano).
  dynamic "secret" {
    for_each = toset(concat(values(each.value.secretos), each.key == "litellm" ? ["litellm-config"] : []))
    content {
      name                = secret.value
      identity            = azurerm_user_assigned_identity.apps.id
      key_vault_secret_id = secret.value == "litellm-config" ? azurerm_key_vault_secret.litellm_config.versionless_id : azurerm_key_vault_secret.secreto[secret.value].versionless_id
    }
  }

  template {
    min_replicas = each.value.min
    max_replicas = each.value.max

    container {
      name   = each.key
      image  = each.value.imagen
      cpu    = each.value.cpu
      memory = each.value.memoria
      args   = each.value.args

      dynamic "env" {
        for_each = merge(each.value.env, { APPLICATIONINSIGHTS_ROLE = each.key })
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = each.value.secretos
        content {
          name        = env.key
          secret_name = env.value
        }
      }

      liveness_probe {
        transport = "HTTP"
        port      = each.value.puerto
        path      = each.value.sonda
      }
      readiness_probe {
        transport = "HTTP"
        port      = each.value.puerto
        path      = each.value.sonda
      }

      dynamic "volume_mounts" {
        for_each = each.value.volumen == null ? [] : [each.value.volumen]
        content {
          name = volume_mounts.value.nombre
          path = volume_mounts.value.ruta
        }
      }
    }

    dynamic "volume" {
      for_each = each.value.volumen == null ? [] : [each.value.volumen]
      content {
        name         = volume.value.nombre
        storage_type = volume.value.tipo
        storage_name = volume.value.tipo == "AzureFile" ? azurerm_container_app_environment_storage.volumen[volume.value.nombre].name : null
      }
    }

    http_scale_rule {
      name                = "solicitudes-concurrentes"
      concurrent_requests = tostring(var.escala.concurrencia)
    }
  }

  ingress {
    external_enabled           = each.value.externo
    target_port                = each.value.puerto
    transport                  = "auto"
    allow_insecure_connections = false
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  lifecycle {
    # El pesaje de tráfico entre revisiones (canary) lo maneja el pipeline de despliegue, no Terraform.
    ignore_changes = [ingress[0].traffic_weight]
  }

  depends_on = [azurerm_role_assignment.kv_apps, azurerm_role_assignment.acr_pull]
}

# Ingesta event-driven: KEDA escala ejecuciones del Job según la cola que llena Event Grid (0 cuando no hay eventos).
resource "azurerm_container_app_job" "ingesta" {
  name                         = "ingesta-worker"
  location                     = azurerm_resource_group.rg.location
  resource_group_name          = azurerm_resource_group.rg.name
  container_app_environment_id = azurerm_container_app_environment.aca.id
  replica_timeout_in_seconds   = 1800
  replica_retry_limit          = 2
  workload_profile_name        = "Consumption"
  tags                         = local.etiquetas

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  dynamic "registry" {
    for_each = startswith(local.propia["ingesta"], local.registro_acr) ? [1] : []
    content {
      server   = local.registro_acr
      identity = azurerm_user_assigned_identity.apps.id
    }
  }

  dynamic "secret" {
    for_each = toset(["redis-url", "mongo-url", "litellm-master-key"])
    content {
      name                = secret.value
      identity            = azurerm_user_assigned_identity.apps.id
      key_vault_secret_id = azurerm_key_vault_secret.secreto[secret.value].versionless_id
    }
  }

  event_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
    scale {
      min_executions              = 0
      max_executions              = 10
      polling_interval_in_seconds = 30
      rules {
        name             = "cola-ingesta"
        custom_rule_type = "azure-queue"
        metadata = {
          queueName   = azurerm_storage_queue.ingesta.name
          queueLength = "1"
          accountName = azurerm_storage_account.datos.name
        }
        identity_id = azurerm_user_assigned_identity.apps.id # KEDA lee la cola con la identidad (sin clave)
      }
    }
  }

  template {
    container {
      name    = "ingesta-worker"
      image   = local.propia["ingesta"]
      cpu     = 2
      memory  = "4Gi" # Whisper small + spaCy
      command = ["python", "-m", "ingesta", "worker"]

      env {
        name  = "INGESTA_QDRANT_URL"
        value = "http://qdrant:80"
      }
      env {
        name  = "OPENAI_BASE_URL"
        value = "http://litellm/v1" # embeddings por el gateway (Azure OpenAI detrás)
      }
      env {
        name  = "EMBEDDING_MODEL"
        value = "embedding"
      }
      env {
        name        = "OPENAI_API_KEY"
        secret_name = "litellm-master-key"
      }
      env {
        name        = "INGESTA_REDIS_URL"
        secret_name = "redis-url"
      }
      env {
        name        = "INGESTA_MONGO_URL"
        secret_name = "mongo-url"
      }
    }
  }

  depends_on = [azurerm_role_assignment.kv_apps, azurerm_role_assignment.acr_pull]
}
