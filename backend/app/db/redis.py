"""
AEGIS — Cliente async de Redis.

Provee un pool de conexiones Redis para uso como broker de Celery,
caché de resultados intermedios y pub/sub para WebSockets.

Seguridad: si REDIS_PASSWORD está definida en el entorno, la URL de
conexión la incluye automáticamente (redis://:password@host:port/0).
"""

from redis.asyncio import Redis

from app.core.config import get_settings

settings = get_settings()

# Pool de conexiones async reutilizable a nivel de módulo.
# Se usa la URL completa de settings (que incluye password si está definida).
redis_client = Redis.from_url(
    settings.redis_url,
    decode_responses=True,  # Decodifica bytes a str automáticamente
    socket_connect_timeout=5,
    socket_timeout=5,
)


def get_redis_client() -> Redis:
    """Retorna la instancia compartida del cliente Redis async."""
    return redis_client
