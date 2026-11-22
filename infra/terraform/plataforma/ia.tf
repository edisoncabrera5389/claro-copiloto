# Azure OpenAI: los mismos modelos de la demo detrás de los alias de LiteLLM (economico, alto, embedding).
# Cambiar de modelo o proveedor = cambiar variables / config de LiteLLM, no código (SAD 2.7).

resource "azurerm_cognitive_account" "openai" {
  #checkov:skip=CKV_AZURE_134:dev sin private endpoints (costo); prod usa privado = true y terraform test lo verifica
  #checkov:skip=CKV_AZURE_236:LiteLLM usa la clave guardada en Key Vault; siguiente paso: Entra ID con la identidad administrada
  #checkov:skip=CKV_AZURE_247:outbound_network_access_restricted = true sin destinos permitidos (checkov no lo detecta con lista vacía)
  #checkov:skip=CKV2_AZURE_22:clave administrada por Microsoft; CMK en la hoja de ruta de cumplimiento
  name                          = "oai-${local.nombre}-${random_string.sufijo.result}"
  location                      = azurerm_resource_group.rg.location
  resource_group_name           = azurerm_resource_group.rg.name
  kind                          = "OpenAI"
  sku_name                      = "S0"
  custom_subdomain_name         = "oai-${local.compacto}"
  public_network_access_enabled = !var.privado
  local_auth_enabled            = true # LiteLLM usa la clave (en Key Vault); siguiente paso: Entra ID con la identidad
  # Prevención de fuga de datos: la cuenta no puede llamar a destinos externos.
  outbound_network_access_restricted = true
  fqdns                              = []
  tags                               = local.etiquetas

  identity {
    type = "SystemAssigned"
  }

  network_acls {
    default_action = var.privado ? "Deny" : "Allow"
  }
}

resource "azurerm_cognitive_deployment" "modelo" {
  for_each             = var.modelos
  name                 = each.key
  cognitive_account_id = azurerm_cognitive_account.openai.id

  model {
    format  = "OpenAI"
    name    = each.value.modelo
    version = each.value.version
  }
  sku {
    name     = each.value.sku
    capacity = each.value.capacidad
  }
}
