"""
AegisRAG — Modelos SQLAlchemy para PostgreSQL.

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
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status", native_enum=False),
        nullable=False,
        default=DocumentStatus.PENDING,
        index=True,
        comment="Estado actual del procesamiento",
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
