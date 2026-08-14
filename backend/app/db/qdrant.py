"""
AegisRAG — Cliente de Qdrant (base de datos vectorial).

Gestiona la conexión al servidor Qdrant para operaciones de
búsqueda densa (embeddings) y esparsa (sparse vectors).
El cliente se reutiliza durante todo el ciclo de vida de la app.
"""

from qdrant_client import QdrantClient, AsyncQdrantClient

from app.core.config import get_settings

settings = get_settings()

# Cliente Qdrant reutilizable a nivel de módulo.
# QdrantClient gestiona su propio pool de conexiones HTTP/gRPC.
qdrant_client = QdrantClient(
    host=settings.qdrant_host,
    port=settings.qdrant_port,
    prefer_grpc=False,  # REST para compatibilidad; gRPC se activa en producción
    timeout=10.0,
)

# Cliente asíncrono para endpoints de FastAPI
async_qdrant_client = AsyncQdrantClient(
    host=settings.qdrant_host,
    port=settings.qdrant_port,
    prefer_grpc=False,
    timeout=10.0,
)


def get_qdrant_client() -> QdrantClient:
    """Retorna la instancia compartida del cliente Qdrant síncrono."""
    return qdrant_client


def get_async_qdrant_client() -> AsyncQdrantClient:
    """Retorna la instancia compartida del cliente Qdrant asíncrono."""
    return async_qdrant_client

