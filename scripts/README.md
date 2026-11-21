# Scripts de utilidad

**Tecnología:** Python (librería estándar; `smoke_mcp.py` usa el cliente FastMCP)  
**Fases del caso:** 4, 5, 6, 7  
**Estado:** en curso

## Responsabilidades

| Script | Uso |
|---|---|
| `bootstrap_data.py` | Copia los insumos de la prueba a `data/raw/`: `py -3.13 scripts/bootstrap_data.py --source "<Insumos_Prueba_Consultor_IA>"` |
| `smoke_mocks.py` | Prueba de humo de los mocks levantados con docker compose (ver abajo) |
| `smoke_mcp.py` | Prueba de humo del servidor MCP por protocolo HTTP (ver abajo) |
| `sembrar_inbox.py` | Carga el corpus en la carpeta vigilada `data/inbox` (ver abajo) |

## sembrar_inbox.py

```powershell
py -3.13 scripts/sembrar_inbox.py                 # carga inicial: documentos (DOCX y PDF), 50 transcripciones, 3 audios
py -3.13 scripts/sembrar_inbox.py --sin-audios    # sin Whisper
py -3.13 scripts/sembrar_inbox.py --catalogo-v2   # demo de frescura: llega el catálogo v2.0
py -3.13 scripts/sembrar_inbox.py --quitar-v2     # ensayo: retira la v2 y vuelve a vigente la v1.0
py -3.13 scripts/sembrar_inbox.py --limpiar       # vacía data/inbox (no toca el índice)
```

- Copia con `copyfile` (la fecha de modificación es la de llegada) y omite lo que ya está igual.
- `--quitar-v2` borra el archivo de la carpeta y ejecuta `python -m ingesta revertir` en el worker.

## smoke_mcp.py

```powershell
docker compose up -d mcp-server
apps/mcp-server/.venv/Scripts/python scripts/smoke_mcp.py     # o: uv run --project apps/mcp-server python scripts/smoke_mcp.py
```

- Usa el cliente FastMCP (por eso corre con el venv de `apps/mcp-server`, no solo con la librería estándar).
- 23 verificaciones: catálogo, PII filtrada, GQ-25 a GQ-28, confirmación firmada (token inventado, cambiado y reusado → rechazados), supervisor para ajustes > $50.000 y circuit breaker con el CRM caído.
- Los tokens se emiten con `docker exec … python -m copiloto_mcp.confirmacion` (simula a la API). Al terminar reinicia los mocks; el circuito del CRM se cierra solo en ≤ 30 s.

## smoke_mocks.py

```powershell
docker compose up -d crm-mock facturacion-mock erp-mock
py -3.13 scripts/smoke_mocks.py                          # completa (~42 verificaciones, ~10 s)
py -3.13 scripts/smoke_mocks.py --muestras-503 0 --sin-logs   # rápida, sin medir el 2 % ni revisar logs
```

- Verifica 401, reglas de negocio (409 de retención, 403 de ajustes), 429 con `Retry-After`, 503 simulado (tasa medida sobre 1.000 llamadas) y que `docker compose logs` no contenga documento, celular, correo ni query string.
- Toma `MOCKS_API_KEY` del entorno o de `.env`; no la imprime.
- Al terminar **siempre** restaura `fail_rate` y el límite de `.env` y reinicia los datos (se pierden tickets, ofertas y ajustes creados): útil como paso previo a la demo.
- Salida: `0` todo OK · `1` alguna verificación falló · `2` los mocks no responden o falta la API key.

## Pruebas

Los propios scripts son verificaciones; el código de los servicios se prueba con pytest en cada `apps/*`.
