output "grupo_recursos" {
  value = azurerm_resource_group.rg.name
}

output "url_frontend" {
  description = "Interfaz del asesor (única app con ingress externo)."
  value       = "https://${azurerm_container_app.app["frontend"].ingress[0].fqdn}"
}

output "registro" {
  description = "ACR al que el pipeline publica las imágenes por SHA."
  value       = azurerm_container_registry.acr.login_server
}

output "key_vault" {
  value = azurerm_key_vault.kv.name
}

output "apps" {
  description = "Apps desplegadas y si su ingress es externo (solo el frontend debe serlo)."
  value       = { for k, a in azurerm_container_app.app : k => a.ingress[0].external_enabled }
}

output "cola_ingesta" {
  value = "${azurerm_storage_account.datos.name}/${azurerm_storage_queue.ingesta.name}"
}
