"""
AEGIS — Servicio de Gestión de Historial y Sesiones de Chat.

Maneja la persistencia de conversaciones en PostgreSQL,
la recuperación de contexto previo para el motor CRAG
y la extracción de consultas frecuentes para soporte y FAQs.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatMessage, ChatSession

logger = logging.getLogger(__name__)


async def get_or_create_session(
    db: AsyncSession,
    session_id: str | None = None,
    title: str | None = None,
) -> ChatSession:
    """
    Obtiene una sesión existente o crea una nueva si no existe.
    Si no se provee session_id, genera un UUIDv4 nuevo.
    """
    if not session_id:
        session_id = str(uuid.uuid4())

    stmt = select(ChatSession).where(ChatSession.id == session_id)
    result = await db.execute(stmt)
    session_obj = result.scalar_one_or_none()

    if not session_obj:
        logger.info("Creando nueva sesión de chat en PostgreSQL: %s", session_id)
        session_obj = ChatSession(
            id=session_id,
            title=title or "Nueva Consulta",
        )
        db.add(session_obj)
        await db.commit()
        await db.refresh(session_obj)

    return session_obj


async def save_chat_message(
    db: AsyncSession,
    session_id: str,
    role: str,
    content: str,
    sources: list[dict] | None = None,
    latency_ms: dict | None = None,
    crag_status: str | None = None,
) -> ChatMessage:
    """
    Guarda un mensaje en la base de datos y actualiza la fecha de la sesión.
    """
    # Asegurar que la sesión exista
    await get_or_create_session(db, session_id)

    msg = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        sources=sources,
        latency_ms=latency_ms,
        crag_status=crag_status,
    )
    db.add(msg)

    # Actualizar fecha de última actividad en la sesión
    stmt_update = (
        select(ChatSession).where(ChatSession.id == session_id)
    )
    res = await db.execute(stmt_update)
    session_obj = res.scalar_one_or_none()
    if session_obj:
        session_obj.updated_at = datetime.now()

    await db.commit()
    await db.refresh(msg)
    return msg


async def get_session_messages(
    db: AsyncSession,
    session_id: str,
    limit: int = 50,
) -> list[ChatMessage]:
    """
    Recupera todos los mensajes de una sesión en orden cronológico ascendente.
    """
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_recent_history_context(
    db: AsyncSession,
    session_id: str,
    limit: int = 6,
) -> list[dict[str, str]]:
    """
    Obtiene los últimos N mensajes formateados como lista de diccionarios
    para alimentar el contexto conversacional del LLM.
    """
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    messages = list(result.scalars().all())
    # Invertir para orden cronológico
    messages.reverse()

    return [
        {"role": msg.role, "content": msg.content}
        for msg in messages
    ]


async def delete_session_history(
    db: AsyncSession,
    session_id: str,
) -> bool:
    """
    Elimina todos los mensajes y la sesión de chat especificada.
    """
    stmt_msg = delete(ChatMessage).where(ChatMessage.session_id == session_id)
    await db.execute(stmt_msg)

    stmt_sess = delete(ChatSession).where(ChatSession.id == session_id)
    await db.execute(stmt_sess)

    await db.commit()
    logger.info("Sesión %s e historial eliminados correctamente", session_id)
    return True


async def get_popular_queries(
    db: AsyncSession,
    limit: int = 5,
) -> list[str]:
    """
    Obtiene consultas recurrentes de los usuarios (rol 'user')
    para generar sugerencias automáticas y FAQs.
    """
    stmt = (
        select(ChatMessage.content, func.count(ChatMessage.id).label("freq"))
        .where(ChatMessage.role == "user")
        .group_by(ChatMessage.content)
        .order_by(desc("freq"))
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [row[0] for row in result.all() if len(row[0]) > 5]
