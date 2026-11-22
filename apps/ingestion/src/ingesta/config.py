"""Configuración por variables de entorno (prefijo INGESTA_; la API key de OpenAI se comparte)."""

from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INGESTA_", extra="ignore", populate_by_name=True)

    # --- Carpeta vigilada (en Azure: Blob Storage + Event Grid) ---
    inbox_dir: Path = Path("/data/inbox")
    poll_s: float = Field(default=3.0, gt=0)

    # --- Cola de eventos (Redis Streams; en Azure: Storage Queue / Service Bus) ---
    redis_url: str = "redis://redis:6379/0"
    stream: str = "ingesta:eventos"
    stream_fallidos: str = "ingesta:fallidos"
    metricas_puerto: int = 9101  # Prometheus (solo red interna)
    grupo: str = "workers"
    max_intentos: int = Field(default=3, ge=1)

    # --- Registro de documentos y linaje ---
    mongo_url: str = "mongodb://mongo:27017"
    mongo_db: str = "copiloto"

    # --- Índice vectorial ---
    qdrant_url: str = "http://qdrant:6333"
    coleccion: str = "conocimiento"

    # --- Embeddings (detrás de una interfaz: OPENAI_BASE_URL permite apuntar a LiteLLM) ---
    openai_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("INGESTA_OPENAI_API_KEY", "OPENAI_API_KEY")
    )
    openai_base_url: str | None = Field(
        default=None, validation_alias=AliasChoices("INGESTA_OPENAI_BASE_URL", "OPENAI_BASE_URL")
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        validation_alias=AliasChoices("INGESTA_EMBEDDING_MODEL", "EMBEDDING_MODEL"),
    )
    embedding_dim: int = 1536

    # --- Fragmentación: ~500 tokens ≈ 2.000 caracteres en español, 15 % de solape ---
    fragmento_chars: int = Field(default=2000, ge=200)
    solape: float = Field(default=0.15, ge=0, lt=0.5)

    # --- OCR y ASR ---
    ocr_min_chars: int = 25  # una página con menos texto que esto se trata como imagen
    tesseract_lang: str = "spa"
    whisper_modelo: str = "small"
    whisper_dir: Path = Path("/modelos/whisper")

    # --- Salud del proceso ---
    latido_dir: Path = Path("/tmp")  # noqa: S108 - archivo de latido dentro del contenedor # nosec B108
