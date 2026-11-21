# Servicios simulados

**Tecnología:** Python 3.12 · FastAPI · uv  
**Fases del caso:** 4  
**Estado:** ✅ CRM, Facturación y ERP con pruebas de contrato

CRM, Facturación y ERP simulados que el servidor MCP consume como si fueran los sistemas reales. Una sola imagen sirve los tres servicios; cuál se levanta lo decide `MOCKS_SERVICIO`.

| Servicio | Puerto | Contrato | Datos |
|---|---|---|---|
| CRM | 8081 | `data/raw/04_apis/crm-api.yaml` (insumo, no versionado) | `crm_clientes.json` (20 clientes) |
| Facturación | 8082 | `data/raw/04_apis/facturacion-api.yaml` (insumo, no versionado) | `facturas.json` (60 facturas) |
| ERP | 8083 | [openapi/erp-api.yaml](openapi/erp-api.yaml) (contrato propio, versionado) | En memoria, arranca vacío |

## Comportamiento transversal

Cada solicitud pasa por: **X-API-Key (401) → límite (429) → falla simulada (503) → handler**.

| Regla | Detalle | Variable |
|---|---|---|
| Autenticación | Cabecera `X-API-Key`, comparación en tiempo constante | `MOCKS_API_KEY` (obligatoria, ≥ 8 caracteres) |
| 429 | Ventana deslizante de 60 s por API key; cabeceras `Retry-After`, `X-RateLimit-Limit` y `X-RateLimit-Remaining`. Las solicitudes sin clave no consumen cupo | `MOCKS_RATE_LIMIT_PER_MIN` (60) |
| 503 | Aleatorio, **antes del handler**: un POST que recibe 503 no tuvo efecto y se puede reintentar sin duplicar | `MOCKS_FAIL_RATE` (0.02), `MOCKS_SEED` |
| Errores | Siempre `{codigo, mensaje, trace_id}`. Las validaciones responden 400 `SOLICITUD_INVALIDA` y nombran los campos, nunca el valor recibido | — |
| Trazas | Reutiliza el trace-id de `traceparent` (W3C) o genera uno; se devuelve en `X-Trace-Id` | — |
| Logs | JSON por solicitud con método, ruta, estado y latencia. **Sin query string**: `numero_documento` viaja en la URL de `GET /clientes`. El access log de uvicorn está desactivado | — |
| Fecha del caso | "Hoy" para la ventana de tickets, los 12 meses de ofertas y las fechas de lo creado | `MOCKS_FECHA_REFERENCIA` (2026-11-18) |

> Por contrato, el CRM devuelve `numero_documento`, `celular` y `email` en la ficha (`GET /clientes/{id}`). Filtrarlos antes de que lleguen al LLM es responsabilidad del servidor MCP.

## Reglas de negocio

| Servicio | Operación | Regla |
|---|---|---|
| CRM | `GET /v1/clientes/{id}/tickets` | `dias` entre 1 y 365 (90 por defecto), más recientes primero |
| CRM | `POST /v1/clientes/{id}/ofertas-retencion` | **409** `CLIENTE_EN_MORA` (mora > 30 días), `OFERTA_RECIENTE` (oferta en los últimos 12 meses) o `CLIENTE_RETIRADO`. La fecha la asigna el CRM |
| CRM | `POST /v1/clientes/{id}/tickets` | Ticket `abierto`; la descripción se guarda pero no se devuelve (texto libre, posible PII) |
| Facturación | `GET /v1/clientes/{id}/facturas` | `limite` entre 1 y 12 (3 por defecto), más recientes primero |
| Facturación | `GET /v1/clientes/{id}/saldo` | `saldo_pendiente` = pendiente + vencido menos ajustes; `proxima_fecha_limite` de la factura pendiente más próxima |
| Facturación | `POST /v1/facturas/{id}/ajustes` | **403** `AJUSTE_REQUIERE_APROBACION` si valor > $50.000 sin `aprobado_por`. El ajuste queda en `factura.ajustes` (extensión) y reduce el saldo |
| ERP | `POST /v1/ordenes-servicio` | Visita técnica, envío o retiro de equipo. Prioritaria a 24 h, estándar a 3 días |
| ERP | `POST /v1/notas-credito` | **409** `NOTA_CREDITO_DUPLICADA` si el `ajuste_id` ya tiene nota (protege los reintentos de n8n) |

## Control de la demo (`/_admin`, requiere API key, fuera del OpenAPI)

Exento del límite y del 503, para poder revertir siempre.

```bash
# Forzar caída total del CRM (circuit breaker en vivo) y restaurarla
curl -X PUT localhost:8081/_admin/config -H "X-API-Key: $MOCKS_API_KEY" -H "Content-Type: application/json" -d '{"fail_rate": 1}'
curl -X PUT localhost:8081/_admin/config -H "X-API-Key: $MOCKS_API_KEY" -H "Content-Type: application/json" -d '{"fail_rate": 0.02}'
# Bajar el límite para provocar 429
curl -X PUT localhost:8081/_admin/config -H "X-API-Key: $MOCKS_API_KEY" -H "Content-Type: application/json" -d '{"rate_limit_per_min": 5}'
# Volver a los datos originales (se pierden tickets, ofertas y ajustes creados)
curl -X POST localhost:8081/_admin/reset -H "X-API-Key: $MOCKS_API_KEY"
```

## Ejecución

```bash
# Con Docker (desde la raíz del repo; requiere .env y data/raw)
docker compose up -d --build crm-mock facturacion-mock erp-mock
# Documentación interactiva: http://localhost:8081/docs · :8082/docs · :8083/docs

# Local, sin Docker (desde apps/mocks)
uv sync
MOCKS_API_KEY=clave-local-123 MOCKS_DATA_DIR=../../data/raw/04_apis/datos_mock uv run python -m mocks crm
```

La imagen es multi-stage (uv en la etapa de build; el runtime solo tiene el venv), corre como el usuario `10001` y trae `HEALTHCHECK` sin curl (`python -m mocks.healthcheck`). En compose, el sistema de archivos es de solo lectura, sin capacidades (`cap_drop: ALL`), con `no-new-privileges`, puertos solo en `127.0.0.1` y datos montados en `/data:ro`.

## Pruebas

```bash
cd apps/mocks
uv run pytest          # 97 pruebas, cobertura ~99 %
uv run ruff check . && uv run ruff format --check .
```

- **Contrato** ([tests/contrato.py](tests/contrato.py)): cada respuesta se valida contra el OpenAPI (código declarado, `Retry-After`, esquema con `$ref` y `nullable`). Si un objeto del contrato no declara `required`, se exigen todas sus propiedades. También se verifica que cada operación del contrato esté implementada.
- **Negocio**: 409 de retención, 403 de ajustes, ventanas y límites, y que un 409, un 403 o un 503 no tengan efecto.
- **Resiliencia**: 401, 429 con ventana deslizante y reloj simulado, tasa de 503 ≈ 2 % con semilla, `/_admin`.
- **PII**: los logs y los errores 400 no contienen documento, celular, correo ni query string.

Las pruebas de CRM y Facturación usan los insumos de `data/raw/04_apis`; si no están, se omiten con aviso. Las del ERP no los necesitan.
