"""
AEGIS — Modelos SQLAlchemy para PostgreSQL.

Define las tablas del sistema. En esta fase:
- Document: rastreo del ciclo de vida de archivos subidos
  (PENDING → PROCESSING → COMPLETED | FAILED).

Las tablas se crean automáticamente al iniciar la app via
Base.metadata.create_all() en el lifespan de FastAPI.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Clase base para todos los modelos ORM del sistema."""
    pass


class DocumentStatus(str, enum.Enum):
    """
    Estados posibles de un documento durante el pipeline de ingestión.
    Hereda de str para serialización automática en JSON.
    """
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Document(Base):
    """
    Modelo que rastrea el estado de procesamiento de cada archivo subido.
    Cada documento pasa por: PENDING → PROCESSING → COMPLETED | FAILED.
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Identificador único del documento",
    )
    filename: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        comment="Nombre original del archivo subido",
    )
    file_path: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        comment="Ruta en disco donde se almacena el archivo",
    )
    document_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pdf",
        comment="Tipo de documento: pdf o youtube",
    )
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status", native_enum=False),
        nullable=False,
        default=DocumentStatus.PENDING,
        index=True,
        comment="Estado actual del procesamiento",
    )
    is_active: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
        server_default="true",
        comment="Indica si el documento está activo y debe usarse en las búsquedas",
    )
    total_chunks: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        default=None,
        comment="Número total de chunks generados tras el procesamiento",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
        comment="Mensaje de error si el procesamiento falla",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Fecha de subida del documento",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Última actualización del registro",
    )

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, filename={self.filename!r}, status={self.status.value})>"


class ChatSession(Base):
    """
    Representa una conversación o hilo de diálogo persistente.
    Identificada por un session_id generado en el navegador/cliente.
    """

    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
        comment="Identificador único de la sesión (UUID string)",
    )
    title: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        default="Nueva Consulta",
        comment="Título descriptivo inferido o por defecto",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Fecha de inicio de la conversación",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Fecha del último mensaje enviado",
    )


class ChatMessage(Base):
    """
    Representa cada turno o mensaje intercambiado en una sesión de chat.
    Almacena el rol (user/assistant), contenido, citas y métricas.
    """

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Identificador único del mensaje",
    )
    session_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        comment="ID de la sesión a la que pertenece este mensaje",
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Rol del emisor: 'user' o 'assistant'",
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Texto del mensaje redactado",
    )
    sources: Mapped[dict | list | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
        comment="Lista de fuentes y citas utilizadas",
    )
    latency_ms: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
        comment="Desglose de latencias CRAG",
    )
    crag_status: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        default=None,
        comment="Estado del flujo CRAG",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Fecha y hora de creación del mensaje",
    )

    def __repr__(self) -> str:
        return f"<ChatMessage(id={self.id}, session_id={self.session_id!r}, role={self.role!r})>"
