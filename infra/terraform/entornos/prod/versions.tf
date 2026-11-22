terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.14"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }

  # Estado remoto en Storage (cifrado, RBAC, versionado). Configuración parcial: el pipeline la completa con
  #   terraform init -backend-config=backend.hcl   (resource_group_name, storage_account_name, container_name, key)
  # Validación sin credenciales: terraform init -backend=false
  backend "azurerm" {
    use_azuread_auth = true
  }
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy = false # un secreto borrado se puede recuperar
    }
  }
  subscription_id = var.subscription_id
  use_oidc        = true # GitHub Actions → Entra ID con federación OIDC: sin secretos de larga duración
}

variable "subscription_id" {
  description = "Suscripción de Azure (la entrega el pipeline; no se versiona)."
  type        = string
}

variable "imagen_registro" {
  description = "Registro de las imágenes. null = el ACR del ambiente; el pipeline puede usar GHCR (paquetes públicos)."
  type        = string
  default     = null
}

variable "imagen_tag" {
  description = "Tag de las imágenes a desplegar (SHA del commit que pasó el CI)."
  type        = string
}

variable "correos_alerta" {
  description = "Destinatarios de las alertas de presupuesto (no se versionan: TF_VAR_correos_alerta)."
  type        = list(string)
}
