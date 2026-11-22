# Red: VNet con subred delegada a Container Apps y subred de private endpoints.
# privado = true (prod): Key Vault, Cosmos, Redis, Storage, OpenAI y ACR solo por private endpoint + DNS privado.

resource "azurerm_virtual_network" "vnet" {
  name                = "vnet-${local.nombre}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  address_space       = [var.red.espacio]
  tags                = local.etiquetas
}

resource "azurerm_subnet" "apps" {
  name                 = "snet-apps"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = [var.red.subred_apps]
  delegation {
    name = "container-apps"
    service_delegation {
      name    = "Microsoft.App/environments"
      actions = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}

resource "azurerm_network_security_group" "apps" {
  name                = "nsg-${local.nombre}-apps"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = local.etiquetas

  # Entrada pública solo por HTTPS hacia el ingress del frontend.
  security_rule {
    name                       = "permitir-https"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_address_prefix      = "Internet"
    source_port_range          = "*"
    destination_address_prefix = var.red.subred_apps
    destination_port_range     = "443"
  }
}

resource "azurerm_subnet_network_security_group_association" "apps" {
  subnet_id                 = azurerm_subnet.apps.id
  network_security_group_id = azurerm_network_security_group.apps.id
}

resource "azurerm_subnet" "privada" {
  name                 = "snet-privada"
  resource_group_name  = azurerm_resource_group.rg.name
  virtual_network_name = azurerm_virtual_network.vnet.name
  address_prefixes     = [var.red.subred_privada]
}

resource "azurerm_network_security_group" "privada" {
  name                = "nsg-${local.nombre}-privada"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  tags                = local.etiquetas

  # Solo la subred de las apps llega a los private endpoints.
  security_rule {
    name                       = "permitir-apps"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_address_prefix      = var.red.subred_apps
    source_port_range          = "*"
    destination_address_prefix = var.red.subred_privada
    destination_port_ranges    = ["443", "10000", "10255"]
  }
  security_rule {
    name                       = "denegar-resto"
    priority                   = 4096
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_address_prefix      = "*"
    source_port_range          = "*"
    destination_address_prefix = "*"
    destination_port_range     = "*"
  }
}

resource "azurerm_subnet_network_security_group_association" "privada" {
  subnet_id                 = azurerm_subnet.privada.id
  network_security_group_id = azurerm_network_security_group.privada.id
}

locals {
  # servicio → (recurso, subrecurso del private endpoint, zona DNS privada)
  endpoints = var.privado ? {
    kv     = { id = azurerm_key_vault.kv.id, sub = "vault", zona = "privatelink.vaultcore.azure.net" }
    cosmos = { id = azurerm_cosmosdb_account.cosmos.id, sub = "MongoDB", zona = "privatelink.mongo.cosmos.azure.com" }
    redis  = { id = azurerm_managed_redis.redis.id, sub = "redisEnterprise", zona = "privatelink.redis.azure.net" }
    blob   = { id = azurerm_storage_account.datos.id, sub = "blob", zona = "privatelink.blob.core.windows.net" }
    queue  = { id = azurerm_storage_account.datos.id, sub = "queue", zona = "privatelink.queue.core.windows.net" }
    file   = { id = azurerm_storage_account.datos.id, sub = "file", zona = "privatelink.file.core.windows.net" }
    openai = { id = azurerm_cognitive_account.openai.id, sub = "account", zona = "privatelink.openai.azure.com" }
    acr    = { id = azurerm_container_registry.acr.id, sub = "registry", zona = "privatelink.azurecr.io" }
  } : {}
}

resource "azurerm_private_dns_zone" "zona" {
  for_each            = local.endpoints
  name                = each.value.zona
  resource_group_name = azurerm_resource_group.rg.name
  tags                = local.etiquetas
}

resource "azurerm_private_dns_zone_virtual_network_link" "enlace" {
  for_each            = local.endpoints
  name                = "lnk-${each.key}"
  private_dns_zone_id = azurerm_private_dns_zone.zona[each.key].id
  virtual_network_id  = azurerm_virtual_network.vnet.id
  tags                = local.etiquetas
}

resource "azurerm_private_endpoint" "pe" {
  for_each            = local.endpoints
  name                = "pe-${local.nombre}-${each.key}"
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  subnet_id           = azurerm_subnet.privada.id
  tags                = local.etiquetas

  private_service_connection {
    name                           = "psc-${each.key}"
    private_connection_resource_id = each.value.id
    subresource_names              = [each.value.sub]
    is_manual_connection           = false
  }
  private_dns_zone_group {
    name                 = "dns-${each.key}"
    private_dns_zone_ids = [azurerm_private_dns_zone.zona[each.key].id]
  }
}
