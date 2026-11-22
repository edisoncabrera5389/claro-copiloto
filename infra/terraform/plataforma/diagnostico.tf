# Diagnóstico a Log Analytics: auditoría de accesos a secretos y operaciones sobre documentos y colas.

resource "azurerm_monitor_diagnostic_setting" "kv" {
  name                       = "diag-kv"
  target_resource_id         = azurerm_key_vault.kv.id
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id

  enabled_log {
    category = "AuditEvent" # quién leyó qué secreto y cuándo
  }
  enabled_metric {
    category = "AllMetrics"
  }
}

resource "azurerm_monitor_diagnostic_setting" "storage" {
  for_each                   = toset(["blobServices", "queueServices"])
  name                       = "diag-${each.key}"
  target_resource_id         = "${azurerm_storage_account.datos.id}/${each.key}/default"
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id

  dynamic "enabled_log" {
    for_each = ["StorageRead", "StorageWrite", "StorageDelete"]
    content {
      category = enabled_log.value
    }
  }
  enabled_metric {
    category = "Transaction"
  }
}
