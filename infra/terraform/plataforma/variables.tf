variable "entorno" {
  description = "Ambiente: dev (costo mínimo, acceso público restringido) o prod (privado, redundante)."
  type        = string
  validation {
    condition     = contains(["dev", "prod"], var.entorno)
    error_message = "entorno debe ser dev o prod."
  }
}

variable "ubicacion" {
  description = "Región de Azure. eastus2: disponibilidad de los modelos de Azure OpenAI (validar cuota al desplegar)."
  type        = string
  default     = "eastus2"
}

variable "prefijo" {
  description = "Prefijo corto de los nombres (minúsculas y números)."
  type        = string
  default     = "ccop"
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,7}$", var.prefijo))
    error_message = "prefijo: 3 a 8 caracteres, minúsculas y números, empezando por letra."
  }
}

variable "privado" {
  description = "true: Key Vault, datos, IA y registro solo por private endpoints (sin acceso público)."
  type        = bool
}

variable "red" {
  description = "Espacio de direcciones de la VNet y subredes (Container Apps exige al menos /23 con delegación)."
  type = object({
    espacio        = string
    subred_apps    = string
    subred_privada = string
  })
  default = {
    espacio        = "10.40.0.0/16"
    subred_apps    = "10.40.0.0/23"
    subred_privada = "10.40.4.0/24"
  }
}

variable "imagen" {
  description = "Registro y tag de las imágenes (el CD publica por SHA del commit)."
  type = object({
    registro = optional(string) # vacío = el ACR que crea este módulo
    tag      = string
  })
}

variable "modelos" {
  description = "Despliegues de Azure OpenAI (alias de LiteLLM → modelo). Capacidad en miles de tokens por minuto."
  type = map(object({
    modelo    = string
    version   = string
    sku       = optional(string, "GlobalStandard")
    capacidad = number
  }))
  default = {
    economico = { modelo = "gpt-4.1-mini", version = "2025-04-14", capacidad = 50 }
    alto      = { modelo = "gpt-4.1", version = "2025-04-14", capacidad = 20 }
    embedding = { modelo = "text-embedding-3-small", version = "1", sku = "Standard", capacidad = 50 }
  }
}

variable "escala" {
  description = "Réplicas mínimas y máximas por app (KEDA por solicitudes concurrentes)."
  type = object({
    minimo_api   = number
    maximo_api   = number
    concurrencia = number
    zonas        = bool
  })
}

variable "desplegar_mocks" {
  description = "Mocks de CRM/Facturación/ERP (solo dev: en prod el MCP apunta a los sistemas reales)."
  type        = bool
  default     = false
}

variable "sistemas" {
  description = "URLs de CRM y Facturación cuando no se despliegan los mocks (integración real detrás del MCP)."
  type = object({
    crm         = optional(string, "")
    facturacion = optional(string, "")
  })
  default = {}
}

variable "presupuesto" {
  description = "FinOps: presupuesto mensual (USD) del grupo de recursos y correos de alerta."
  type = object({
    monto_mensual = number
    correos       = list(string)
    inicio        = string # primer día de un mes, RFC3339 (p. ej. 2026-12-01T00:00:00Z)
  })
  validation {
    condition     = can(regex("^\\d{4}-\\d{2}-01T00:00:00Z$", var.presupuesto.inicio))
    error_message = "presupuesto.inicio debe ser el primer día de un mes (AAAA-MM-01T00:00:00Z)."
  }
}

variable "retencion_logs_dias" {
  description = "Retención de Log Analytics (auditoría técnica; la auditoría de negocio vive 5 años en Cosmos)."
  type        = number
  default     = 30
}

variable "etiquetas" {
  description = "Etiquetas adicionales (centro de costo, dueño)."
  type        = map(string)
  default     = {}
}
