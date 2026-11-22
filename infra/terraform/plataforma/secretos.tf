# Key Vault (RBAC) + secretos: los internos se generan aquí y los de servicios salen de los propios recursos.
# Ningún secreto pasa por variables ni por el repo. Las apps los leen con su identidad administrada.
# El estado de Terraform contiene estos valores: backend en Storage con cifrado, RBAC y sin acceso público.

resource "azurerm_key_vault" "kv" {
  #checkov:skip=CKV_AZURE_189:dev sin private endpoints (costo); prod usa privado = true y terraform test lo verifica
  #checkov:skip=CKV_AZURE_109:dev sin private endpoints (costo); prod usa privado = true y terraform test lo verifica
  #checkov:skip=CKV2_AZURE_32:dev sin private endpoints (costo); prod usa privado = true y terraform test lo verifica
  name                          = "kv-${local.compacto}"
  location                      = azurerm_resource_group.rg.location
  resource_group_name           = azurerm_resource_group.rg.name
  tenant_id                     = data.azurerm_client_config.actual.tenant_id
  sku_name                      = local.prod ? "premium" : "standard"
  rbac_authorization_enabled    = true
  purge_protection_enabled      = local.prod
  soft_delete_retention_days    = local.prod ? 90 : 7
  public_network_access_enabled = !var.privado
  tags                          = local.etiquetas

  network_acls {
    default_action = var.privado ? "Deny" : "Allow"
    bypass         = "AzureServices"
  }
  lifecycle {
    prevent_destroy = true # secretos de la plataforma
  }
}

resource "azurerm_role_assignment" "kv_apps" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets User" # solo lectura de secretos
  principal_id         = azurerm_user_assigned_identity.apps.principal_id
}

resource "azurerm_role_assignment" "kv_despliegue" {
  scope                = azurerm_key_vault.kv.id
  role_definition_name = "Key Vault Secrets Officer" # quien ejecuta Terraform (pipeline con OIDC)
  principal_id         = data.azurerm_client_config.actual.object_id
}

resource "random_password" "interno" {
  for_each = toset(["jwt-secret", "confirmacion-secret", "litellm-master-key", "mocks-api-key", "demo-password", "n8n-encryption-key"])
  length   = each.key == "demo-password" ? 20 : 48
  special  = false
}

locals {
  secretos = merge(
    { for k, v in random_password.interno : k => v.result },
    {
      "openai-api-key"       = azurerm_cognitive_account.openai.primary_access_key
      "openai-endpoint"      = azurerm_cognitive_account.openai.endpoint
      "mongo-url"            = azurerm_cosmosdb_account.cosmos.primary_mongodb_connection_string
      "redis-url"            = "rediss://:${azurerm_managed_redis.redis.default_database[0].primary_access_key}@${azurerm_managed_redis.redis.hostname}:10000/0"
      "appinsights-conexion" = azurerm_application_insights.appi.connection_string
    }
  )
}

resource "azurerm_key_vault_secret" "secreto" {
  for_each        = nonsensitive(toset(keys(local.secretos)))
  name            = each.key
  value           = local.secretos[each.key]
  key_vault_id    = azurerm_key_vault.kv.id
  content_type    = "text/plain"
  expiration_date = "2027-12-31T00:00:00Z" # rotación: revisar antes del vencimiento (alerta de Key Vault)
  depends_on      = [azurerm_role_assignment.kv_despliegue]
}
