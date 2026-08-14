"""
AegisRAG — Configuración centralizada del backend.

Usa pydantic-settings para cargar variables de entorno desde .env
con validación automática de tipos y valores por defecto seguros.
Patrón Singleton via lru_cache para evitar re-parsear en cada request.
"""

from functools import lru_cache
from typing import Annotated

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración global de la aplicación AegisRAG."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        # Ignora variables extra en .env que no estén mapeadas
        extra="ignore",
    )

    # ── API ────────────────────────────────────────────────
    api_title: str = "AegisRAG"
    api_version: str = "0.1.0"
    api_debug: bool = False
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:8000",
    ]

    # ── PostgreSQL ─────────────────────────────────────────
    postgres_user: str = "aegisrag"
    postgres_password: str = "aegisrag_secret"
    postgres_db: str = "aegisrag"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    @computed_field  # type: ignore[prop-decorator]
    @property
    def postgres_dsn(self) -> str:
        """DSN async para SQLAlchemy (driver asyncpg)."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Qdrant ─────────────────────────────────────────────
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_grpc_port: int = 6334

    # ── Redis ──────────────────────────────────────────────
    redis_host: str = "localhost"
    redis_port: int = 6379

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        """URL de conexión para Redis (broker Celery y caché)."""
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    # ── Embeddings ─────────────────────────────────────────
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    sparse_embedding_model: str = "prithivida/Splade_PP_en_v1"

    # ── Reranker ───────────────────────────────────────────
    reranker_model: str = "BAAI/bge-reranker-base"
    crag_relevance_threshold: float = 0.10

    # ── LLM ────────────────────────────────────────────────
    llm_provider: str = "ollama"
    llm_model: str = "llama3"
    openai_api_key: str | None = None
    groq_api_key: str | None = None
    ollama_base_url: str = "http://127.0.0.1:11434"

    # ── Ingestión de documentos ────────────────────────────
    upload_dir: str = "uploads"
    chunk_size: int = 500
    chunk_overlap: int = 50
    qdrant_collection: str = "aegis_chunks"

    # ── PostgreSQL Sync (para Celery workers) ──────────────
    @computed_field  # type: ignore[prop-decorator]
    @property
    def postgres_dsn_sync(self) -> str:
        """DSN síncrono para SQLAlchemy (driver psycopg2, usado por Celery)."""
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Retorna la instancia singleton de Settings.
    Se cachea para no re-parsear el .env en cada invocación.
    """
    return Settings()
