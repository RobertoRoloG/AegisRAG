"""
AegisRAG — Endpoints de gestión de documentos.

Provee los endpoints para subir documentos PDF y consultar
su estado de procesamiento. La ingestión real se delega
a un worker de Celery para no bloquear el hilo de FastAPI.
"""

import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.params import Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Document, DocumentStatus
from app.db.postgres import get_db_session
from app.workers.ingestion import process_pdf_task

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/documents", tags=["Documents"])


# ── Modelos de respuesta ──────────────────────────────────


class DocumentItem(BaseModel):
    """Modelo simplificado para listados de documentos."""

    document_id: str
    filename: str
    status: str
    total_chunks: int | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime



class DocumentUploadResponse(BaseModel):
    """Respuesta tras subir un documento."""

    document_id: str
    filename: str
    status: str


class DocumentStatusResponse(BaseModel):
    """Respuesta con el estado actual de un documento."""

    document_id: str
    filename: str
    status: str
    total_chunks: int | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


# ── Constantes ─────────────────────────────────────────────

ALLOWED_EXTENSIONS = {".pdf"}
MAX_FILE_SIZE_MB = 50


# ── Endpoints ──────────────────────────────────────────────


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Subir un documento PDF para ingestión",
    description=(
        "Recibe un archivo PDF, lo almacena en disco, crea un registro "
        "en PostgreSQL y dispara una tarea asíncrona de Celery para "
        "procesarlo (parsing, chunking, embeddings, Qdrant)."
    ),
)
async def upload_document(
    file: UploadFile,
    session: AsyncSession = Depends(get_db_session),
) -> DocumentUploadResponse:
    """
    Sube un documento PDF para procesamiento asíncrono.
    Devuelve inmediatamente el document_id para consultar el estado después.
    """
    # ── Validar extensión ──────────────────────────────────
    if file.filename is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo debe tener un nombre",
        )

    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Solo se aceptan archivos PDF. Extensión recibida: '{file_ext}'",
        )

    # ── Validar tamaño (leer contenido) ────────────────────
    content = await file.read()
    file_size_mb = len(content) / (1024 * 1024)
    if file_size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Archivo demasiado grande: {file_size_mb:.1f}MB (máx: {MAX_FILE_SIZE_MB}MB)",
        )

    # ── Guardar archivo en disco ───────────────────────────
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Nombre único para evitar colisiones
    file_id = uuid.uuid4()
    safe_filename = f"{file_id}_{file.filename}"
    file_path = upload_dir / safe_filename

    file_path.write_bytes(content)
    logger.info("Archivo guardado: %s (%0.1f MB)", file_path, file_size_mb)

    # ── Crear registro en PostgreSQL ───────────────────────
    document = Document(
        id=file_id,
        filename=file.filename,
        file_path=str(file_path),
        status=DocumentStatus.PENDING,
    )
    session.add(document)
    # El commit se ejecuta automáticamente en get_db_session al salir del yield

    # Forzar flush para que el ID esté disponible antes del commit
    await session.flush()

    # ── Disparar tarea Celery ──────────────────────────────
    process_pdf_task.delay(str(file_id))
    logger.info(
        "Tarea de ingestión encolada para documento %s (%s)",
        file_id,
        file.filename,
    )

    return DocumentUploadResponse(
        document_id=str(file_id),
        filename=file.filename,
        status=DocumentStatus.PENDING.value,
    )


@router.get(
    "/{document_id}/status",
    response_model=DocumentStatusResponse,
    summary="Consultar estado de procesamiento de un documento",
    description="Devuelve el estado actual del documento y sus metadatos.",
)
async def get_document_status(
    document_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> DocumentStatusResponse:
    """Consulta el estado de procesamiento de un documento por su ID."""
    # Validar que el ID sea un UUID válido
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ID de documento inválido: '{document_id}'",
        )

    # Consultar en PostgreSQL
    result = await session.execute(
        select(Document).where(Document.id == doc_uuid)
    )
    document = result.scalar_one_or_none()

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Documento no encontrado: '{document_id}'",
        )

    return DocumentStatusResponse(
        document_id=str(document.id),
        filename=document.filename,
        status=document.status.value,
        total_chunks=document.total_chunks,
        error_message=document.error_message,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


@router.get(
    "/",
    response_model=list[DocumentItem],
    summary="Listar todos los documentos cargados",
    description="Devuelve el listado de todos los documentos y su estado actual.",
)
async def list_documents(
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    """Lista todos los documentos ordenados por fecha de creación descendente."""
    result = await session.execute(
        select(Document).order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()
    return [
        {
            "document_id": str(d.id),
            "filename": d.filename,
            "status": d.status.value,
            "total_chunks": d.total_chunks,
            "error_message": d.error_message,
            "created_at": d.created_at,
            "updated_at": d.updated_at,
        }
        for d in docs
    ]


@router.get(
    "/{document_id}/file",
    summary="Visualizar o descargar el PDF original",
    description="Sirve el archivo físico del PDF original almacenado en disco.",
)
async def get_document_file(
    document_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> FileResponse:
    """Retorna el archivo físico del documento solicitado."""
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ID de documento inválido: '{document_id}'",
        )

    result = await session.execute(
        select(Document).where(Document.id == doc_uuid)
    )
    document = result.scalar_one_or_none()

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Documento no encontrado: '{document_id}'",
        )

    file_path = Path(document.file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El archivo físico del documento no existe en el disco del servidor",
        )

    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline"},
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_200_OK,
    summary="Eliminar un documento y todo su contenido indexado",
    description="Elimina el archivo físico de PDF, los vectores asociados en Qdrant y el registro en PostgreSQL.",
)
async def delete_document(
    document_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    """Elimina el documento de todos los sistemas (disco, Qdrant y PostgreSQL)."""
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ID de documento inválido: '{document_id}'",
        )

    result = await session.execute(
        select(Document).where(Document.id == doc_uuid)
    )
    document = result.scalar_one_or_none()

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Documento no encontrado: '{document_id}'",
        )

    # 1. Eliminar archivo físico en disco
    try:
        file_path = Path(document.file_path)
        if file_path.exists():
            file_path.unlink()
            logger.info("Archivo PDF eliminado del almacenamiento: %s", file_path)
    except Exception as exc:
        logger.error("Error al eliminar archivo físico de PDF '%s': %s", document.file_path, exc)

    # 2. Eliminar vectores correspondientes en Qdrant
    try:
        from qdrant_client import models as qdrant_models
        from app.db.qdrant import get_async_qdrant_client
        async_qdrant = get_async_qdrant_client()
        
        await async_qdrant.delete(
            collection_name=settings.qdrant_collection,
            points_selector=qdrant_models.Filter(
                must=[
                    qdrant_models.FieldCondition(
                        key="doc_id",
                        match=qdrant_models.MatchValue(value=document_id)
                    )
                ]
            )
        )
        logger.info("Puntos del documento %s purgados de Qdrant", document_id)
    except Exception as exc:
        logger.error("Fallo al eliminar vectores de Qdrant del documento %s: %s", document_id, exc)

    # 3. Eliminar registro en PostgreSQL
    await session.delete(document)
    logger.info("Documento %s eliminado de PostgreSQL", document_id)

    return {
        "status": "success",
        "message": f"Documento '{document.filename}' y vectores de Qdrant eliminados correctamente.",
    }

