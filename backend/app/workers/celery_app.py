"""
AegisRAG — Configuración de la instancia Celery.

Define la aplicación Celery conectada a Redis como broker y backend.
Los workers se lanzan con:
    celery -A app.workers.celery_app worker --loglevel=info --pool=solo
"""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

# Instancia Celery con Redis como broker (cola de tareas) y backend (resultados)
celery_app = Celery(
    "aegisrag",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

# Configuración del comportamiento de las tareas
celery_app.conf.update(
    # Serialización JSON para compatibilidad y seguridad
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Reintentos: las tareas de ingestión no se reintentan automáticamente
    # (el retry se gestiona manualmente desde el endpoint)
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Registrar explícitamente los módulos que contienen tareas
celery_app.conf.imports = (
    "app.workers.ingestion",
)
