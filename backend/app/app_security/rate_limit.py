"""
AEGIS — Rate Limiting con SlowAPI + Redis.

Configura un limitador de velocidad global respaldado en Redis para que los
límites sean efectivos incluso con múltiples workers Uvicorn.

Límites aplicados:
- POST /documents/upload      → 20 peticiones / minuto por IP
- POST /documents/sync-youtube → 5 peticiones / minuto por IP
- Resto de endpoints          → sin límite (lectura/chat)

Si Redis no está disponible, SlowAPI cae a un backend en memoria de forma
silenciosa (no rompe la app, solo pierde coordinación entre workers).

Uso en FastAPI:
    from app.security.rate_limit import limiter
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @router.post("/upload")
    @limiter.limit("20/minute")
    async def upload_document(request: Request, ...):
        ...
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import get_settings

settings = get_settings()

# Usar Redis como storage distribuido para que el límite sea global entre
# todos los workers. Si no hay contraseña configurada, la URL no la incluye.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.redis_url,
    default_limits=[],  # Sin límite global; se aplica por endpoint
)
