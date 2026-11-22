# FinOps (SAD 2.15): presupuesto mensual con alertas (80 % real, 100 % pronosticado). El costo por turno del LLM
# lo registra la API en cada traza y en Prometheus; aquí se controla el gasto de la infraestructura.

resource "azurerm_consumption_budget_resource_group" "mensual" {
  name              = "budget-${local.nombre}"
  resource_group_id = azurerm_resource_group.rg.id
  amount            = var.presupuesto.monto_mensual
  time_grain        = "Monthly"

  time_period {
    start_date = var.presupuesto.inicio
  }

  notification {
    enabled        = true
    operator       = "GreaterThan"
    threshold      = 80
    threshold_type = "Actual"
    contact_emails = var.presupuesto.correos
  }
  notification {
    enabled        = true
    operator       = "GreaterThan"
    threshold      = 100
    threshold_type = "Forecasted"
    contact_emails = var.presupuesto.correos
  }
}
