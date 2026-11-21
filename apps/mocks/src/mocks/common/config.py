"""Configuración por variables de entorno (prefijo MOCKS_)."""

from datetime import date
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MOCKS_", extra="ignore")

    # Obligatoria: sin clave el servicio no arranca.
    api_key: SecretStr = Field(min_length=8)
    # Probabilidad de responder 503 simulado (0.02 = 2 %).
    fail_rate: float = Field(default=0.02, ge=0.0, le=1.0)
    # Límite de solicitudes por minuto y por API key (ventana deslizante).
    rate_limit_per_min: int = Field(default=60, ge=1)
    # Carpeta con crm_clientes.json y facturas.json.
    data_dir: Path = Path("/data")
    # "Hoy" del caso: ventanas de tickets, 12 meses de ofertas y fechas de lo creado.
    fecha_referencia: date = date(2026, 11, 18)
    # Semilla opcional para que el 503 aleatorio sea reproducible (pruebas).
    seed: int | None = None
