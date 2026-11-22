"""Configuración por variables de entorno (prefijo ML_)."""

from datetime import date

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ML_", extra="ignore")

    mlflow_tracking_uri: str = "http://mlflow:5000"
    alias: str = "produccion"  # alias del Model Registry que se sirve
    mongo_url: str = "mongodb://mongo:27017"
    mongo_db: str = "copiloto"
    # "Hoy" del caso: ventana de 90 días de tickets al construir las variables desde la ficha del CRM
    fecha_referencia: date = date(2026, 11, 18)
    umbral_confianza: float = Field(default=0.7, ge=0, le=1)  # bajo esto la API usa su respaldo
    ventana_drift: int = Field(default=500, ge=10)  # últimas N inferencias para el PSI
