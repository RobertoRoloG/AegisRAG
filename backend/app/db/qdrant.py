"""
AEGIS — Cliente de Qdrant (base de datos vectorial).

Gestiona la conexión al servidor Qdrant para operaciones de
búsqueda densa (embeddings) y esparsa (sparse vectors).
El cliente se reutiliza durante todo el ciclo de vida de la app.

Seguridad: si QDRANT_API_KEY está definida en el entorno, se pasa
como api_key al cliente para autenticación en despliegues con Qdrant Cloud
o instancias con autenticación habilitada.
"""

from qdrant_client import QdrantClient, AsyncQdrantClient

from app.core.config import get_settings

settings = get_settings()

# Parámetros comunes del cliente; api_key es None en local (sin auth)
_qdrant_kwargs = {
    "host": settings.qdrant_host,
    "port": settings.qdrant_port,
    "prefer_grpc": False,  # REST para compatibilidad; gRPC se activa en producción
    "timeout": 10.0,
}
if settings.qdrant_api_key:
    _qdrant_kwargs["api_key"] = settings.qdrant_api_key

# Cliente Qdrant reutilizable a nivel de módulo.
# QdrantClient gestiona su propio pool de conexiones HTTP/gRPC.
qdrant_client = QdrantClient(**_qdrant_kwargs)

# Cliente asíncrono para endpoints de FastAPI
async_qdrant_client = AsyncQdrantClient(**_qdrant_kwargs)


def get_qdrant_client() -> QdrantClient:
    """Retorna la instancia compartida del cliente Qdrant síncrono."""
    return qdrant_client


def get_async_qdrant_client() -> AsyncQdrantClient:
    """Retorna la instancia compartida del cliente Qdrant asíncrono."""
    return async_qdrant_client
