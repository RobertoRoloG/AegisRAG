"""
AegisRAG — Cliente async de Redis.

Provee un pool de conexiones Redis para uso como broker de Celery,
caché de resultados intermedios y pub/sub para WebSockets.
"""

from redis.asyncio import Redis

from app.core.config import get_settings

settings = get_settings()

# Pool de conexiones async reutilizable a nivel de módulo.
# redis.asyncio.Redis gestiona internamente el connection pool.
redis_client = Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    db=0,
    decode_responses=True,  # Decodifica bytes a str automáticamente
    socket_connect_timeout=5,
    socket_timeout=5,
)


def get_redis_client() -> Redis:
    """Retorna la instancia compartida del cliente Redis async."""
    return redis_client
