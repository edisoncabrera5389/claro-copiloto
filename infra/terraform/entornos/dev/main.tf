# Ambiente dev: costo mínimo, mocks de sistemas, acceso público a los servicios administrados (sin private endpoints).
module "plataforma" {
  source = "../../plataforma"

  entorno         = "dev"
  privado         = false
  desplegar_mocks = true
  imagen          = { registro = var.imagen_registro, tag = var.imagen_tag }

  escala = {
    minimo_api   = 1
    maximo_api   = 3
    concurrencia = 20
    zonas        = false
  }

  presupuesto = {
    monto_mensual = 300
    correos       = var.correos_alerta
    inicio        = "2026-12-01T00:00:00Z"
  }

  etiquetas = { centro_costo = "demo-ia" }
}

output "url_frontend" {
  value = module.plataforma.url_frontend
}

output "registro" {
  value = module.plataforma.registro
}
