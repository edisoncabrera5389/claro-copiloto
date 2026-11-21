# Servidor MCP

**Tecnología:** Python · FastMCP  
**Fases del caso:** 4, 7  
**Estado:** pendiente

## Responsabilidades

- Tools de lectura: obtenerCliente, listarServicios, listarTickets, listarFacturas, obtenerSaldo
- Tools de escritura (requieren confirmación): crearTicket, registrarOfertaRetencion, aplicarAjuste
- Skill evaluarRetencion: reglas de la política en código determinístico
- Reintentos con backoff, Retry-After, timeouts, circuit breaker y filtrado de PII

## Pruebas

pytest + respx contra los mocks
