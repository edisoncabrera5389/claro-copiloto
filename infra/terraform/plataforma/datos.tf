# Datos: fuentes documentales con evento de ingesta, memoria larga/auditoría (Cosmos Mongo) y memoria corta (Redis).

# --- Storage: contenedor de fuentes (carpeta vigilada → Blob + Event Grid) y volúmenes de Qdrant/MLflow/n8n
resource "azurerm_storage_account" "datos" {
  #checkov:skip=CKV_AZURE_59:dev sin private endpoints (costo); prod usa privado = true y terraform test lo verifica
  #checkov:skip=CKV2_AZURE_33:dev sin private endpoints (costo); prod usa privado = true y terraform test lo verifica
  #checkov:skip=CKV2_AZURE_40:los volúmenes Azure Files de Container Apps exigen clave de cuenta (solo la usa el entorno ACA)
  #checkov:skip=CKV2_AZURE_1:clave administrada por Microsoft; CMK en la hoja de ruta de cumplimiento
  #checkov:skip=CKV_AZURE_33:registro de la cola por diagnóstico a Log Analytics (azurerm_monitor_diagnostic_setting)
  #checkov:skip=CKV2_AZURE_21:registro de blobs por diagnóstico a Log Analytics (azurerm_monitor_diagnostic_setting)
  name                            = "st${local.compacto}"
  location                        = azurerm_resource_group.rg.location
  resource_group_name             = azurerm_resource_group.rg.name
  account_tier                    = "Standard"
  account_replication_type        = local.prod ? "ZRS" : "LRS"
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  public_network_access           = var.privado ? "Disabled" : "Enabled" # azurerm 5: reemplaza *_enabled
  # Azure Files para los volúmenes de Container Apps aún exige clave de cuenta (la usa solo el entorno de ACA).
  shared_access_key_enabled = true
  tags                      = local.etiquetas

  sas_policy {
    expiration_period = "01.00:00:00" # un SAS emitido no puede durar más de 1 día
  }

  blob_properties {
    versioning_enabled = true # versionado de documentos: el índice cita versión, el blob guarda la historia
    delete_retention_policy {
      days = local.prod ? 30 : 7
    }
    container_delete_retention_policy {
      days = local.prod ? 30 : 7
    }
  }
  lifecycle {
    prevent_destroy = true # documentos originales y versionados: irrecuperables
  }
}

resource "azurerm_storage_container" "fuentes" {
  #checkov:skip=CKV2_AZURE_21:lecturas de blobs registradas por el diagnóstico de blobServices (diagnostico.tf)
  name                  = "fuentes"
  storage_account_id    = azurerm_storage_account.datos.id
  container_access_type = "private"
  lifecycle {
    prevent_destroy = true # fuentes oficiales con su historial de versiones
  }
}

# tflint-ignore: azurerm_resources_missing_prevent_destroy # eventos transitorios (Event Grid reintenta)
resource "azurerm_storage_queue" "ingesta" {
  name               = "ingesta-eventos"
  storage_account_id = azurerm_storage_account.datos.id
}

# tflint-ignore: azurerm_resources_missing_prevent_destroy # índice de Qdrant reconstruible desde las fuentes
resource "azurerm_storage_share" "volumen" {
  for_each           = toset(["qdrant", "mlflow", "n8n"])
  name               = each.key
  storage_account_id = azurerm_storage_account.datos.id
  quota              = each.key == "qdrant" ? 50 : 10
}

# Evento de frescura: Blob creado/borrado en "fuentes" → cola → Container Apps Job de ingesta (KEDA).
resource "azurerm_eventgrid_system_topic" "fuentes" {
  name                = "evgt-${local.nombre}-fuentes"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  source_resource_id  = azurerm_storage_account.datos.id
  topic_type          = "Microsoft.Storage.StorageAccounts"
  tags                = local.etiquetas
}

resource "azurerm_eventgrid_system_topic_event_subscription" "ingesta" {
  name                 = "evgs-ingesta"
  system_topic         = azurerm_eventgrid_system_topic.fuentes.name
  resource_group_name  = azurerm_resource_group.rg.name
  included_event_types = ["Microsoft.Storage.BlobCreated", "Microsoft.Storage.BlobDeleted"]

  subject_filter {
    subject_begins_with = "/blobServices/default/containers/${azurerm_storage_container.fuentes.name}/"
  }
  storage_queue_endpoint {
    storage_account_id = azurerm_storage_account.datos.id
    queue_name         = azurerm_storage_queue.ingesta.name
  }
  retry_policy {
    max_delivery_attempts = 10
    event_time_to_live    = 1440
  }
}

resource "azurerm_role_assignment" "storage_apps" {
  for_each = toset(["Storage Blob Data Contributor", "Storage Queue Data Contributor"])

  scope                = azurerm_storage_account.datos.id
  role_definition_name = each.key
  principal_id         = azurerm_user_assigned_identity.apps.principal_id
}

# --- Cosmos DB (API MongoDB): memoria larga, auditoría (5 años), feedback, registro de documentos
resource "azurerm_cosmosdb_account" "cosmos" {
  #checkov:skip=CKV_AZURE_101:dev sin private endpoints (costo); prod usa privado = true y terraform test lo verifica
  #checkov:skip=CKV_AZURE_99:dev sin private endpoints (costo); prod usa privado = true y terraform test lo verifica
  #checkov:skip=CKV_AZURE_100:clave administrada por Microsoft; CMK en la hoja de ruta de cumplimiento
  name                               = "cosmos-${local.compacto}"
  location                           = azurerm_resource_group.rg.location
  resource_group_name                = azurerm_resource_group.rg.name
  offer_type                         = "Standard"
  kind                               = "MongoDB"
  mongo_server_version               = "7.0"
  public_network_access_enabled      = !var.privado
  automatic_failover_enabled         = local.prod
  local_authentication_enabled       = true # el driver Mongo usa cadena de conexión (guardada en Key Vault)
  minimal_tls_version                = "Tls12"
  access_key_metadata_writes_enabled = false # las claves no pueden cambiar la configuración (solo RBAC de ARM)
  tags                               = local.etiquetas

  capabilities {
    name = "EnableMongo"
  }
  dynamic "capabilities" {
    for_each = local.prod ? [] : ["EnableServerless"] # dev: paga por uso
    content {
      name = capabilities.value
    }
  }

  consistency_policy {
    consistency_level = "Session"
  }
  geo_location {
    location          = azurerm_resource_group.rg.location
    failover_priority = 0
    zone_redundant    = local.prod
  }
  backup {
    type                = local.prod ? "Continuous" : "Periodic"
    tier                = local.prod ? "Continuous30Days" : null
    interval_in_minutes = local.prod ? null : 1440
    retention_in_hours  = local.prod ? null : 48
    storage_redundancy  = local.prod ? null : "Local"
  }
  lifecycle {
    prevent_destroy = true # auditoría regulatoria (5 años), memoria larga y feedback
  }
}

resource "azurerm_cosmosdb_mongo_database" "copiloto" {
  name                = "copiloto"
  resource_group_name = azurerm_resource_group.rg.name
  account_name        = azurerm_cosmosdb_account.cosmos.name
  dynamic "autoscale_settings" {
    for_each = local.prod ? [4000] : []
    content {
      max_throughput = autoscale_settings.value
    }
  }
}

# --- Azure Managed Redis: memoria corta (TTL 2 h), propuestas pendientes, caché semántico y límites
# tflint-ignore: azurerm_resources_missing_prevent_destroy # caché y memoria corta (TTL 2 h): datos efímeros
resource "azurerm_managed_redis" "redis" {
  name                      = "redis-${local.nombre}-${random_string.sufijo.result}"
  location                  = azurerm_resource_group.rg.location
  resource_group_name       = azurerm_resource_group.rg.name
  sku_name                  = local.prod ? "Balanced_B1" : "Balanced_B0"
  high_availability_enabled = local.prod
  public_network_access     = var.privado ? "Disabled" : "Enabled"
  tags                      = local.etiquetas

  default_database {
    access_keys_authentication_enabled = true
    client_protocol                    = "Encrypted"
    eviction_policy                    = "VolatileLRU" # solo expulsa claves con TTL (memoria corta y caché)
  }
}
