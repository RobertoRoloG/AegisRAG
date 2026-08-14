"""
AegisRAG — Endpoint de Health Check.

Verifica la conectividad con los tres servicios de infraestructura:
- PostgreSQL: ejecuta SELECT 1
- Qdrant: consulta la lista de colecciones
- Redis: ejecuta PING

Devuelve el estado individual de cada servicio y un estado global.
Si algún servicio falla, el status global es "degraded" (HTTP 503).
"""

from typing import Literal

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.db.postgres import async_session_factory
from app.db.qdrant import get_qdrant_client
from app.db.redis import get_redis_client

router = APIRouter(tags=["Health"])

# Tipos posibles para el estado de un servicio individual
ServiceStatus = Literal["up", "down"]


class HealthResponse(BaseModel):
    """Modelo de respuesta del health check."""

    status: Literal["healthy", "degraded"]
    postgres: ServiceStatus
    qdrant: ServiceStatus
    redis: ServiceStatus
    details: dict[str, str] | None = None


async def _check_postgres() -> tuple[ServiceStatus, str]:
    """Verifica la conexión a PostgreSQL ejecutando una consulta trivial."""
    try:
        async with async_session_factory() as session:
            result = await session.execute(text("SELECT 1"))
            result.scalar_one()
        return "up", ""
    except Exception as exc:
        return "down", str(exc)


async def _check_qdrant() -> tuple[ServiceStatus, str]:
    """Verifica la conexión a Qdrant consultando las colecciones."""
    try:
        client = get_qdrant_client()
        # get_collections es una operación ligera que valida conectividad
        client.get_collections()
        return "up", ""
    except Exception as exc:
        return "down", str(exc)


async def _check_redis() -> tuple[ServiceStatus, str]:
    """Verifica la conexión a Redis con PING."""
    try:
        client = get_redis_client()
        pong = await client.ping()
        if not pong:
            return "down", "PING no devolvió respuesta"
        return "up", ""
    except Exception as exc:
        return "down", str(exc)


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Check del sistema",
    description="Verifica conectividad con PostgreSQL, Qdrant y Redis.",
)
async def health_check() -> JSONResponse:
    """
    Ejecuta checks de conectividad contra los tres servicios.
    Retorna 200 si todos están operativos, 503 si alguno falla.
    """
    pg_status, pg_error = await _check_postgres()
    qd_status, qd_error = await _check_qdrant()
    rd_status, rd_error = await _check_redis()

    # Estado global: healthy solo si los tres están up
    all_up = all(s == "up" for s in [pg_status, qd_status, rd_status])
    global_status: Literal["healthy", "degraded"] = "healthy" if all_up else "degraded"

    # Incluir detalles de error solo si algún servicio falla
    details: dict[str, str] | None = None
    if not all_up:
        details = {}
        if pg_error:
            details["postgres_error"] = pg_error
        if qd_error:
            details["qdrant_error"] = qd_error
        if rd_error:
            details["redis_error"] = rd_error

    response = HealthResponse(
        status=global_status,
        postgres=pg_status,
        qdrant=qd_status,
        redis=rd_status,
        details=details,
    )

    http_status = status.HTTP_200_OK if all_up else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(
        content=response.model_dump(),
        status_code=http_status,
    )
