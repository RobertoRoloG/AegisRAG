"""
AegisRAG — Entrypoint principal de FastAPI.

Configura la instancia de la aplicación con:
- Middleware CORS para el frontend Next.js
- Eventos de lifecycle (startup/shutdown) para gestionar conexiones
- Creación automática de tablas en PostgreSQL
- Inicialización de la colección en Qdrant
- Inclusión de routers de API versionados
"""

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.api.v1.health import router as health_router
from app.api.v1.documents import router as documents_router
from app.api.v1.chat import router as chat_router
from app.db.models import Base
from app.db.postgres import engine
from app.db.redis import redis_client
from app.services.vector_store import ensure_collection

logger = logging.getLogger(__name__)
settings = get_settings()

# Configurar logging básico
logging.basicConfig(
    level=logging.DEBUG if settings.api_debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Gestiona el ciclo de vida de la aplicación.
    - Startup: crea tablas, inicializa colección Qdrant, crea directorio uploads.
    - Shutdown: cierra pools de conexiones de forma ordenada.
    """
    # ── Startup ────────────────────────────────────────────

    # Crear tablas de PostgreSQL si no existen
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Tablas de PostgreSQL verificadas/creadas")

    # Crear colección en Qdrant si no existe
    try:
        ensure_collection()
    except Exception as exc:
        logger.warning(
            "No se pudo inicializar la colección en Qdrant: %s "
            "(el servicio puede no estar disponible aún)",
            exc,
        )

    # Crear directorio de uploads si no existe
    upload_path = Path(settings.upload_dir)
    upload_path.mkdir(parents=True, exist_ok=True)
    logger.info("Directorio de uploads: %s", upload_path.resolve())

    yield

    # ── Shutdown ───────────────────────────────────────────
    await engine.dispose()
    await redis_client.aclose()
    logger.info("Conexiones cerradas correctamente")


app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description=(
        "AegisRAG — Sistema empresarial de Corrective RAG "
        "con búsqueda híbrida, re-ranking e ingestión asíncrona."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Middleware CORS ────────────────────────────────────────
# Permite requests desde los orígenes configurados (frontend Next.js)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────
# Todos los endpoints de la API v1 se montan bajo /api/v1
app.include_router(health_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
