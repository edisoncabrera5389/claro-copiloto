"""Configuración por variables de entorno (prefijo MCP_)."""

from datetime import date

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_", extra="ignore")

    # --- Sistemas ---
    crm_url: str = "http://crm-mock:8081/v1"
    facturacion_url: str = "http://facturacion-mock:8082/v1"
    mocks_api_key: SecretStr = Field(min_length=8)

    # --- Confirmación de acciones con efecto (compartido con la API, que emite los tokens) ---
    confirmacion_secret: SecretStr = Field(min_length=32)
    confirmacion_ttl_s: int = Field(default=300, ge=30, le=3600)

    # --- Reglas ---
    fecha_referencia: date = date(2026, 11, 18)  # "hoy" del caso, igual que los mocks

    # --- Resiliencia del cliente HTTP ---
    http_timeout_s: float = Field(default=4.0, gt=0)
    reintentos: int = Field(default=3, ge=1, le=6)  # intentos totales por llamada
    backoff_base_s: float = Field(default=0.2, ge=0)
    backoff_max_s: float = Field(default=2.0, ge=0)
    # Un 429 con Retry-After mayor a esto se devuelve de inmediato: esperar 60 s rompe el p95 de 8 s.
    retry_after_max_s: float = Field(default=3.0, ge=0)
    breaker_fallas: int = Field(default=5, ge=1)  # fallas consecutivas que abren el circuito
    breaker_abierto_s: float = Field(default=30.0, gt=0)

    # --- Servidor ---
    host: str = "0.0.0.0"  # noqa: S104 - escucha dentro del contenedor # nosec B104
    port: int = 8090
