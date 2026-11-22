# Grupo de recursos, observabilidad, identidad de las apps y registro de imágenes.

data "azurerm_client_config" "actual" {}

resource "random_string" "sufijo" {
  length  = 5
  special = false
  upper   = false
}

locals {
  prod     = var.entorno == "prod"
  nombre   = "${var.prefijo}-${var.entorno}"
  compacto = "${var.prefijo}${var.entorno}${random_string.sufijo.result}" # storage/ACR/KV: sin guiones, únicos
  etiquetas = merge(var.etiquetas, {
    proyecto   = "claro-copiloto"
    entorno    = var.entorno
    gestionado = "terraform"
  })
}

resource "azurerm_resource_group" "rg" {
  name     = "rg-${local.nombre}"
  location = var.ubicacion
  tags     = local.etiquetas
}

# --- Observabilidad (SAD 2.12: Log Analytics + Application Insights; Prometheus/Grafana administrados en prod)
resource "azurerm_log_analytics_workspace" "logs" {
  name                = "log-${local.nombre}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku                 = "PerGB2018"
  retention_in_days   = var.retencion_logs_dias
  daily_quota_gb      = local.prod ? -1 : 1 # dev: tope diario de ingesta (FinOps)
  tags                = local.etiquetas
}

resource "azurerm_application_insights" "appi" {
  name                = "appi-${local.nombre}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  workspace_id        = azurerm_log_analytics_workspace.logs.id
  application_type    = "web"
  tags                = local.etiquetas
}

resource "azurerm_monitor_workspace" "prometheus" {
  count               = local.prod ? 1 : 0
  name                = "amw-${local.nombre}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = local.etiquetas
}

resource "azurerm_dashboard_grafana" "grafana" {
  count                 = local.prod ? 1 : 0
  name                  = "graf-${local.nombre}"
  location              = azurerm_resource_group.rg.location
  resource_group_name   = azurerm_resource_group.rg.name
  grafana_major_version = 12
  identity {
    type = "SystemAssigned"
  }
  azure_monitor_workspace_integrations {
    resource_id = azurerm_monitor_workspace.prometheus[0].id
  }
  tags = local.etiquetas
}

# --- Identidad administrada de las apps: sin credenciales en el código ni en variables de entorno
resource "azurerm_user_assigned_identity" "apps" {
  name                = "id-${local.nombre}-apps"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = local.etiquetas
}

# --- Registro de imágenes (Premium en prod: private endpoint y geo-replicación)
resource "azurerm_container_registry" "acr" {
  #checkov:skip=CKV_AZURE_139:dev sin private endpoints (costo); prod usa privado = true y terraform test lo verifica
  #checkov:skip=CKV_AZURE_163:las imágenes se escanean con Trivy en el CI (gate de 0 CVEs críticas) antes de publicarse
  #checkov:skip=CKV_AZURE_164:content trust (Notary v1) está deprecado en ACR; la procedencia la da el tag = SHA del CI
  #checkov:skip=CKV_AZURE_233:zonas solo en prod (Premium); el SKU Basic de dev no las admite
  #checkov:skip=CKV_AZURE_165:una sola región; geo-replicación cuando haya despliegue multi-región
  name                          = "acr${local.compacto}"
  location                      = azurerm_resource_group.rg.location
  resource_group_name           = azurerm_resource_group.rg.name
  sku                           = local.prod ? "Premium" : "Basic"
  admin_enabled                 = false
  public_network_access_enabled = !var.privado
  # Funciones Premium (solo prod): limpieza de manifiestos sin tag, cuarentena, endpoints de datos y zonas.
  retention_policy_in_days  = local.prod ? 7 : null
  quarantine_policy_enabled = local.prod
  data_endpoint_enabled     = local.prod
  zone_redundancy_enabled   = local.prod
  tags                      = local.etiquetas
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.acr.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.apps.principal_id
}
