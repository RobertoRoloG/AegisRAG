"""
AEGIS — Configuración de la instancia Celery.

Define la aplicación Celery conectada a Redis como broker y backend.
Los workers se lanzan con:
    celery -A app.workers.celery_app worker --loglevel=info --pool=solo

Seguridad aplicada:
- Serialización exclusivamente JSON (pickle deshabilitado → sin RCE)
- task_reject_on_worker_lost: evita pérdida silenciosa de tareas si el worker muere
- worker_max_tasks_per_child: recicla el proceso worker tras N tareas para evitar
  memory leaks en ingestiones largas de PDFs
"""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

# Instancia Celery con Redis como broker (cola de tareas) y backend (resultados)
celery_app = Celery(
    "AEGIS",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

# Configuración del comportamiento de las tareas
celery_app.conf.update(
    # ── Serialización segura (pickle completamente deshabilitado) ──────────
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # ── Timezone ──────────────────────────────────────────────────────────
    timezone="UTC",
    enable_utc=True,
    # ── Fiabilidad de tareas ───────────────────────────────────────────────
    # Confirma el ACK de Redis solo después de que la tarea termina con éxito.
    # Evita pérdida silenciosa de mensajes si el worker muere a mitad de tarea.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Un worker procesa una tarea a la vez (evita saturación de CPU/VRAM)
    worker_prefetch_multiplier=1,
    # Reciclar el proceso worker tras 200 tareas para liberar memoria acumulada
    # (útil en ingestiones largas con modelos de embeddings cargados en RAM)
    worker_max_tasks_per_child=200,
)

# Registrar explícitamente los módulos que contienen tareas
celery_app.conf.imports = (
    "app.workers.ingestion",
)

# Planificación periódica de tareas (Celery Beat)
celery_app.conf.beat_schedule = {
    "sync-youtube-videos-every-2-hours": {
        "task": "AEGIS.sync_youtube_videos",
        "schedule": 7200.0,  # Sincroniza cada 2 horas
    }
}
