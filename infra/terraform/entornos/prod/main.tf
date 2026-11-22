# Ambiente prod: todo privado (private endpoints), zonas de disponibilidad, réplicas mínimas 2 para el canary,
# integración real con CRM/Facturación detrás del MCP (sin mocks).
module "plataforma" {
  source = "../../plataforma"

  entorno         = "prod"
  privado         = true
  desplegar_mocks = false
  imagen          = { registro = var.imagen_registro, tag = var.imagen_tag }

  sistemas = {
    crm         = var.url_crm
    facturacion = var.url_facturacion
  }

  modelos = {
    economico = { modelo = "gpt-4.1-mini", version = "2025-04-14", capacidad = 300 }
    alto      = { modelo = "gpt-4.1", version = "2025-04-14", capacidad = 100 }
    embedding = { modelo = "text-embedding-3-small", version = "1", sku = "Standard", capacidad = 150 }
  }

  escala = {
    minimo_api   = 2  # dos revisiones conviven durante el canary sin perder capacidad
    maximo_api   = 30 # KEDA por solicitudes concurrentes (SAD 2.14: escala horizontal)
    concurrencia = 50
    zonas        = true
  }

  presupuesto = {
    monto_mensual = 3000
    correos       = var.correos_alerta
    inicio        = "2026-12-01T00:00:00Z"
  }

  retencion_logs_dias = 90
  etiquetas           = { centro_costo = "atencion-cliente" }
}

variable "url_crm" {
  description = "API del CRM real (detrás del MCP)."
  type        = string
}

variable "url_facturacion" {
  description = "API de Facturación real (detrás del MCP)."
  type        = string
}

output "url_frontend" {
  value = module.plataforma.url_frontend
}

output "registro" {
  value = module.plataforma.registro
}
