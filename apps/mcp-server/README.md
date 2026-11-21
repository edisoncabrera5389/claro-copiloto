# Servidor MCP

**Tecnología:** Python 3.12 · FastMCP 4 (HTTP streamable) · httpx · uv  
**Fases del caso:** 4, 7  
**Estado:** ✅ tools, skill de retención y confirmación firmada

Único punto de acceso del agente a CRM y Facturación (ADR-03). Expone 11 tools en `http://localhost:8090/mcp` y `/health` con el estado de los circuitos.

## Tools

| Tool | Tipo | Qué hace |
|---|---|---|
| `buscarCliente` | lectura | Por tipo y número de documento → solo `cliente_id`, `nombre`, `estado` |
| `obtenerCliente` | lectura | Ficha (servicios, mora, tickets, ofertas 12 m) **sin documento, celular ni correo** |
| `listarServicios`, `listarTickets`, `listarFacturas`, `obtenerSaldo`, `obtenerFactura` | lectura | Proxy tipado a CRM y Facturación con validación de entrada (`^C-\d{4}$`, `dias` 1–365, `limite` 1–12) |
| `evaluarRetencion` | skill (lectura) | POL-RET-2026 v3.1 en código: elegibilidad, tramo, ofertas RET-A/RET-B por servicio, visita prioritaria previa, Mesa Especializada, Promo Fibra 500 |
| `crearTicket` | escritura | Ticket en el CRM; documento, celular y correo de la descripción se enmascaran |
| `registrarOfertaRetencion` | escritura | Reevalúa la política; **la descripción sale de la política**, no del LLM (POL-RET numeral 5) |
| `aplicarAjuste` | escritura | > $50.000 exige confirmación de **supervisor** (queda como `aprobado_por`) |

Las tools de lectura llevan `readOnlyHint: true`; las de escritura, `false`.

## Confirmación firmada de acciones con efecto

El agente propone y el asesor decide, y el MCP lo hace cumplir criptográficamente:

1. El agente llama la tool de escritura **sin** `token_confirmacion` → recibe `{"estado": "requiere_confirmacion", "parametros", "huella", "requiere_rol", "resumen"}`. **No se ejecuta nada.**
2. La UI muestra la propuesta; el asesor (o supervisor) confirma; **la API** firma un token.
3. La API llama la tool con el token → el MCP verifica y ejecuta el POST **una sola vez**.

```
token   = base64url(payload) "." base64url(HMAC-SHA256(MCP_CONFIRMACION_SECRET, base64url(payload)))
payload = {"v":1, "acc":accion, "h":huella, "sub":asesor_id, "rol":"asesor"|"supervisor", "iat", "exp", "jti"}
huella  = sha256(json.dumps({"accion":accion, "parametros":parametros}, sort_keys=True, separators=(",",":"), ensure_ascii=False))
```

| Rechazo | Cuándo |
|---|---|
| `CONFIRMACION_INVALIDA` | Firma incorrecta, token inventado o alterado (p. ej. cambiar `rol` a supervisor) |
| `CONFIRMACION_NO_COINCIDE` | Otra acción o parámetros distintos a los confirmados |
| `CONFIRMACION_EXPIRADA` | Pasaron más de `MCP_CONFIRMACION_TTL_S` (300 s) |
| `CONFIRMACION_YA_USADA` | El `jti` ya se usó (en memoria; en producción, Redis con TTL) |
| `AJUSTE_REQUIERE_APROBACION` | Ajuste > $50.000 con token de rol `asesor` |

Si el sistema rechaza la escritura con certeza de que no se aplicó (503, sin conexión, circuito abierto), el token se libera y sirve para reintentar; si el resultado es incierto (timeout), queda consumido. El LLM nunca ve el secreto, así que **no puede ejecutar una escritura por su cuenta**.

Mientras no exista la API, el token se emite con la CLI dentro del contenedor, que tiene el secreto:

```powershell
docker exec claro-copiloto-mcp-server-1 python -m copiloto_mcp.confirmacion --accion crearTicket --asesor A-001 --parametros '<"parametros" de la propuesta>'
```

## Skill `evaluarRetencion`: decisiones de implementación

| Regla | Implementación |
|---|---|
| Antigüedad = servicio más antiguo activo | `round(días / 30,4375)`: coincide con `antiguedad_meses` del CRM en los 20 clientes y con el golden (C-1004 = 30, C-1013 = 26) |
| Tramos | > 24 · 12–24 (inclusive) · < 12 |
| < 12 meses | Según las columnas de la matriz: Hogar → RET-A repetidor × 6; Móvil → RET-B 10 GB × 3 |
| Upgrade "al siguiente plan" | [escalera_planes.json](src/copiloto_mcp/escalera_planes.json) (CAT-2026 v1 y v2): Fibra 300 → 500 → 900; Max 25/30 → 60 → Ilimitado. Triple Play 500 y Fibra 900 no tienen superior |
| ≥ 3 tickets técnicos en 90 días | El descuento queda **no disponible** hasta que exista un ticket técnico `prioritaria` abierto (la visita); el upgrade sigue disponible |
| Promo Fibra 500 (no acumulable con descuentos) | El CRM no la marca: se infiere por un Hogar Fibra 500 activado hace < 3 meses o por el concepto en la última factura |
| Alto valor ≥ $150.000 | Sugiere transferir a la Mesa de Retención Especializada (opcional, como dice la política) |
| Facturación caída | La evaluación continúa con una advertencia (la promo se verifica solo con el CRM) |

## Resiliencia hacia los sistemas

| Situación | Comportamiento |
|---|---|
| 503, 5xx, timeout, sin conexión (GET) | Hasta 3 intentos con backoff exponencial con jitter (0,2 s → 2 s) |
| 429 | Respeta `Retry-After` si es ≤ 3 s; si es mayor, falla rápido con `LIMITE_EXCEDIDO` y `reintentar_en_s` (esperar 60 s rompe el p95 de 8 s). No abre el circuito |
| POST | Solo se reintenta ante 503 o sin conexión (garantía de no ejecución); nunca ante timeout o 500 |
| 4xx de negocio (400/403/404/409) | Sin reintento; llega al agente como `CODIGO: mensaje (sistema=crm)` |
| 5 fallas seguidas | Circuito **abierto** 30 s por sistema → `CIRCUITO_ABIERTO` sin llamar; luego semiabierto con una prueba |
| Trazas | Un `traceparent` W3C por operación, igual en todos sus reintentos |

Logs: una línea JSON por tool (`tool`, `ok`, `estado` o `error`, `ms`), **nunca los argumentos**.

## Ejecución

```powershell
docker compose up -d --build mcp-server        # levanta también crm-mock y facturacion-mock
Invoke-RestMethod http://127.0.0.1:8090/health
```

Variables: `MCP_MOCKS_API_KEY`, `MCP_CONFIRMACION_SECRET` (obligatorias), `MCP_CONFIRMACION_TTL_S`, `MCP_CRM_URL`, `MCP_FACTURACION_URL`, `MCP_FECHA_REFERENCIA`, `MCP_REINTENTOS`, `MCP_RETRY_AFTER_MAX_S`, `MCP_BREAKER_FALLAS`, `MCP_BREAKER_ABIERTO_S` (ver [config.py](src/copiloto_mcp/config.py)).

Imagen multi-stage, usuario `10001`, `HEALTHCHECK`, solo lectura y sin capacidades en compose; puerto solo en `127.0.0.1`.

## Pruebas

```powershell
cd apps/mcp-server
uv run pytest                      # 102 unitarias con datos sintéticos + 6 de integración si los mocks están arriba
uv run pytest -m integracion       # solo integración (GQ-25 a GQ-28 con los datos reales)
uv run ruff check . ; uv run ruff format --check .
# Desde la raíz, por protocolo MCP real contra los contenedores (23 verificaciones):
apps/mcp-server/.venv/Scripts/python scripts/smoke_mcp.py
```

- **Unitarias** (sin insumos, aptas para CI): PII y redacción, circuit breaker, reintentos, Retry-After, seguridad de los POST (respx), tokens (firma, expiración, parámetros, uso único, rol alterado), POL-RET regla por regla y el servidor por protocolo MCP en memoria.
- **Integración**: casos del golden con tools (GQ-25 plan y saldo, GQ-26 C-1004, GQ-27 C-1007, GQ-28 C-1013 con el flujo completo de confirmación), ajuste con supervisor y antigüedad = CRM en los 20 clientes.
