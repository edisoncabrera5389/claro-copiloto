"""Configuración por variables de entorno (prefijo API_; los secretos compartidos usan su nombre global)."""

from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _alias(*nombres: str) -> AliasChoices:
    return AliasChoices(*nombres)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="API_", extra="ignore", populate_by_name=True)

    # --- Autenticación (JWT local por rol; en producción: SSO corporativo) ---
    jwt_secret: SecretStr = Field(min_length=32, validation_alias=_alias("API_JWT_SECRET", "JWT_SECRET"))
    jwt_expira_min: int = Field(default=480, validation_alias=_alias("API_JWT_EXPIRA_MIN", "JWT_EXPIRES_MIN"))
    # usuario:rol:nombre — usuarios de demostración con una sola contraseña (API_DEMO_PASSWORD)
    usuarios_demo: str = (
        "A-001:asesor:Asesor Demo,A-002:asesor:Asesora Demo,"
        "SUP-001:supervisor:Supervisora Demo,ADM-001:admin:Admin Demo"
    )
    demo_password: SecretStr = Field(min_length=8)
    rate_limit_por_min: int = Field(default=30, ge=1)

    # --- LLM Gateway (LiteLLM, formato OpenAI) ---
    llm_base_url: str = "http://litellm:4000/v1"
    llm_api_key: SecretStr = Field(validation_alias=_alias("API_LLM_API_KEY", "LITELLM_MASTER_KEY"))
    modelo_economico: str = "economico"
    modelo_alto: str = "alto"
    modelo_embedding: str = "embedding"
    # Precios de referencia (USD por millón de tokens) para el costo por turno; validar con la lista vigente.
    precio_entrada_economico: float = 0.40
    precio_salida_economico: float = 1.60
    precio_entrada_alto: float = 2.00
    precio_salida_alto: float = 8.00

    # --- Retriever ---
    qdrant_url: str = "http://qdrant:6333"
    coleccion: str = "conocimiento"
    k_candidatos: int = 20  # top-N denso + top-N BM25 antes de fusionar
    k_final: int = 5  # fragmentos que llegan al LLM
    # Medido en la máquina de demo (CPU): bge-reranker-v2-m3-int8 tarda ~5 s con 20 candidatos y ~2 s con 10;
    # jina-v2-multilingual, igual. Rompe la meta de TTFT ≤ 2 s → desactivado por defecto (ver evaluación).
    reranker_activo: bool = False
    reranker_modelo: str = "BAAI/bge-reranker-v2-m3-int8"
    k_rerank: int = 10
    modelos_dir: Path = Path("/modelos/fastembed")
    # Bajo este valor (coseno o sigmoide del reranker): "no encontrado → escalar". Calibrado con el golden.
    umbral_confianza: float = Field(default=0.25, ge=0, le=1)

    # --- Servidor MCP y confirmación de acciones ---
    mcp_url: str = "http://mcp-server:8090/mcp"
    confirmacion_secret: SecretStr = Field(
        min_length=32, validation_alias=_alias("API_CONFIRMACION_SECRET", "MCP_CONFIRMACION_SECRET")
    )
    confirmacion_ttl_s: int = Field(
        default=300, validation_alias=_alias("API_CONFIRMACION_TTL_S", "MCP_CONFIRMACION_TTL_S")
    )

    # --- Memoria y auditoría ---
    redis_url: str = "redis://redis:6379/1"
    mongo_url: str = "mongodb://mongo:27017"
    mongo_db: str = "copiloto"
    memoria_ttl_s: int = 7200  # memoria corta: 2 h
    memoria_turnos: int = 6

    # --- Límites del agente (SAD 2.3) ---
    max_pasos: int = 6
    max_llamadas_misma_tool: int = 3
