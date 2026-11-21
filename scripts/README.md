# Scripts de utilidad

**Tecnología:** Python (solo librería estándar)  
**Fases del caso:** 4  
**Estado:** en curso

## Responsabilidades

| Script | Uso |
|---|---|
| `bootstrap_data.py` | Copia los insumos de la prueba a `data/raw/`: `py -3.13 scripts/bootstrap_data.py --source "<Insumos_Prueba_Consultor_IA>"` |
| `smoke_mocks.py` | Prueba de humo de los mocks levantados con docker compose (ver abajo) |

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
