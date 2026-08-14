"""
AegisRAG — Conexión asíncrona y síncrona a PostgreSQL.

Configura el AsyncEngine y la session factory de SQLAlchemy 2.0.
Las sesiones se gestionan como dependency de FastAPI con patrón yield
para asegurar rollback automático en caso de excepción.

Adicionalmente provee un engine síncrono para los workers de Celery,
que operan en procesos separados sin event loop async.
"""

from collections.abc import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# ── Async (FastAPI) ────────────────────────────────────────
# Motor async con pool de conexiones configurado para producción
engine = create_async_engine(
    settings.postgres_dsn,
    echo=settings.api_debug,  # Loguea SQL solo en modo debug
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,  # Detecta conexiones muertas antes de usarlas
)

# Factory de sesiones async (no expira objetos al commit para evitar lazy loads)
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ── Sync (Celery Workers) ─────────────────────────────────
# Los workers de Celery ejecutan en procesos separados sin
# event loop async. Usan psycopg2 (driver síncrono).
sync_engine = create_engine(
    settings.postgres_dsn_sync,
    echo=settings.api_debug,
    pool_size=5,
    max_overflow=5,
    pool_pre_ping=True,
)

sync_session_factory = sessionmaker(
    bind=sync_engine,
    class_=Session,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency de FastAPI que provee una sesión de base de datos.
    Hace commit implícito si no hay errores, rollback en caso contrario.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
