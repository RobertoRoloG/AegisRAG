"""
AEGIS — Endpoints de gestión de documentos.

Provee los endpoints para subir documentos PDF y consultar
su estado de procesamiento. La ingestión real se delega
a un worker de Celery para no bloquear el hilo de FastAPI.
"""

import logging
import uuid
import xml.etree.ElementTree as ET
import httpx
import re

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.params import Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Document, DocumentStatus
from app.db.postgres import get_db_session
from app.app_security.file_validator import sanitize_filename, validate_pdf_magic_bytes
from app.app_security.rate_limit import limiter
from app.workers.ingestion import process_pdf_task, process_youtube_transcript_task

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/documents", tags=["Documents"])


# ── Modelos de respuesta ──────────────────────────────────


class DocumentItem(BaseModel):
    """Modelo simplificado para listados de documentos."""

    document_id: str
    filename: str
    file_path: str | None = None
    status: str
    document_type: str | None = "pdf"
    total_chunks: int | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    is_active: bool = True


class SyncYoutubeRequest(BaseModel):
    channel_url: str | None = None
    full_scan: bool = False


class YoutubeTranscriptUploadResponse(BaseModel):
    document_id: str
    filename: str
    status: str


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
    document_type: str | None = "pdf"
    total_chunks: int | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    is_active: bool = True


class ToggleDocumentResponse(BaseModel):
    """Respuesta tras activar/desactivar un documento."""

    document_id: str
    is_active: bool


# ── Constantes ─────────────────────────────────────────────

ALLOWED_EXTENSIONS = {".pdf"}
ALLOWED_TRANSCRIPT_EXTENSIONS = {".vtt", ".txt"}


# ── Endpoints ──────────────────────────────────────────────


@router.post(
    "/youtube-transcript",
    response_model=YoutubeTranscriptUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Importar una transcripción de YouTube con tiempos (.vtt o .txt)",
)
@limiter.limit("20/minute")
async def upload_youtube_transcript(
    request: Request,
    video_url: str = Form(...),
    title: str = Form(...),
    transcript_file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
) -> YoutubeTranscriptUploadResponse:
    """Importa un VTT/TXT con timestamps generado fuera del servidor y lo indexa como videotutorial."""
    video_match = re.search(r"(?:v=|/v/|embed/|youtu\.be/)([\w-]{11})", video_url)
    if not video_match:
        raise HTTPException(status_code=400, detail="La URL de YouTube no es válida")

    extension = Path(transcript_file.filename or "").suffix.lower()
    if extension not in ALLOWED_TRANSCRIPT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="La transcripción debe ser un archivo .vtt o .txt")

    transcript = (await transcript_file.read()).decode("utf-8-sig", errors="replace")
    if not transcript.strip():
        raise HTTPException(status_code=400, detail="La transcripción está vacía")

    video_id = video_match.group(1)
    normalized_url = f"https://www.youtube.com/watch?v={video_id}"
    existing = await session.execute(select(Document).where(Document.file_path == normalized_url))
    document = existing.scalar_one_or_none()
    if document is None:
        document = Document(
            id=uuid.uuid4(),
            filename=title.strip() or f"Vídeo {video_id}",
            file_path=normalized_url,
            document_type="youtube",
            status=DocumentStatus.PENDING,
        )
        session.add(document)
    else:
        document.filename = title.strip() or document.filename
        document.status = DocumentStatus.PENDING
        document.total_chunks = None
        document.error_message = None

    document_id = str(document.id)
    await session.commit()
    process_youtube_transcript_task.delay(document_id, transcript)

    return YoutubeTranscriptUploadResponse(
        document_id=document_id,
        filename=document.filename,
        status=DocumentStatus.PENDING.value,
    )


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
@limiter.limit("20/minute")
async def upload_document(
    request: Request,
    file: UploadFile,
    session: AsyncSession = Depends(get_db_session),
) -> DocumentUploadResponse:
    """
    Sube un documento PDF para procesamiento asíncrono.
    Devuelve inmediatamente el document_id para consultar el estado después.
    """
    # ── Validar nombre ──────────────────────────────────────
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

    # ── Leer contenido y validar magic bytes ───────────────
    # La validación de tamaño se omite deliberadamente: la gestión de
    # archivos grandes es responsabilidad del equipo operacional.
    content = await file.read()
    validate_pdf_magic_bytes(content)

    # ── Guardar archivo en disco ───────────────────────────
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Nombre único y sanitizado en disco (previene Path Traversal).
    # El nombre original se preserva en la base de datos para mostrarlo al usuario.
    file_id = uuid.uuid4()
    safe_filename = f"{file_id}_{sanitize_filename(file.filename)}"
    file_path = upload_dir / safe_filename

    file_path.write_bytes(content)
    logger.info("Archivo guardado: %s (%0.1f MB)", file_path, len(content) / (1024 * 1024))

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
        document_type=getattr(document, 'document_type', 'pdf'),
        total_chunks=document.total_chunks,
        error_message=document.error_message,
        created_at=document.created_at,
        updated_at=document.updated_at,
        is_active=document.is_active,
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
            "file_path": d.file_path,
            "status": d.status.value,
            "document_type": getattr(d, 'document_type', 'pdf'),
            "total_chunks": d.total_chunks,
            "error_message": d.error_message,
            "created_at": d.created_at,
            "updated_at": d.updated_at,
            "is_active": d.is_active,
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


@router.patch(
    "/{document_id}/toggle",
    response_model=ToggleDocumentResponse,
    summary="Activar o desactivar un documento",
    description="Permite activar o desactivar un documento (PDF o vídeo) para que se use o se ignore en las búsquedas.",
)
async def toggle_document(
    document_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> ToggleDocumentResponse:
    """Cambia el estado de activación de un documento por su ID."""
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

    document.is_active = not document.is_active
    # get_db_session hará el commit automáticamente al finalizar
    logger.info("Documento %s cambiado de estado de activacion a %s", document_id, document.is_active)
    
    return ToggleDocumentResponse(
        document_id=str(document.id),
        is_active=document.is_active,
    )


@router.get(
    "/youtube-channel",
    summary="Obtener ID y URL del canal de YouTube configurado por defecto",
    description="Devuelve el canal de YouTube configurado en las variables de entorno del servidor.",
)
async def get_youtube_channel_info():
    """Retorna la configuración actual del canal de YouTube."""
    return {
        "channel_id": settings.youtube_channel_id,
        "channel_url": f"https://www.youtube.com/channel/{settings.youtube_channel_id}"
    }


async def get_youtube_video_title(video_url: str) -> str:
    """Obtiene el título público de un vídeo de YouTube mediante oembed."""
    try:
        oembed_url = f"https://www.youtube.com/oembed?url={video_url}&format=json"
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(oembed_url)
            if res.status_code == 200:
                return res.json().get("title", "Vídeo de YouTube")
    except Exception:
        pass
    return "Vídeo de YouTube"


@router.post(
    "/sync-youtube",
    status_code=status.HTTP_200_OK,
    summary="Sincronizar dinámicamente videotutoriales de YouTube",
    description="Consulta el canal de YouTube o procesa un vídeo individual directo e inicia su indexación."
)
@limiter.limit("5/minute")
async def sync_youtube_videos(
    request: Request,
    payload: SyncYoutubeRequest | None = None,
    session: AsyncSession = Depends(get_db_session),
):
    from app.workers.ingestion import process_youtube_video_task

    # 1. Comprobar si es una URL de un vídeo individual
    if payload and payload.channel_url:
        video_match = re.search(r"(?:v=|\/v\/|embed\/|youtu\.be\/)([\w-]{11})", payload.channel_url)
        if video_match:
            video_id = video_match.group(1)
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            
            # Comprobar si ya existe
            result = await session.execute(select(Document).where(Document.file_path == video_url))
            existe = result.scalar_one_or_none()
            if existe:
                if existe.status == DocumentStatus.FAILED:
                    # Permitir reintentar si falló antes
                    existe.status = DocumentStatus.PENDING
                    await session.flush()
                    process_youtube_video_task.delay(str(existe.id))
                    return {"status": "success", "message": f"Vídeo '{existe.filename}' reencolado para indexación.", "added": 1}
                return {"status": "success", "message": f"El vídeo '{existe.filename}' ya estaba indexado.", "added": 0}
            
            # Obtener título real del vídeo
            title = await get_youtube_video_title(video_url)
            new_id = uuid.uuid4()
            nuevo_doc = Document(
                id=new_id,
                filename=title,
                file_path=video_url,
                document_type="youtube",
                status=DocumentStatus.PENDING
            )
            session.add(nuevo_doc)
            await session.flush()
            
            process_youtube_video_task.delay(str(new_id))
            return {"status": "success", "message": f"Vídeo '{title}' encolado con éxito para indexación.", "added": 1}

    # 2. Si no es un vídeo individual, realizar sincronización del canal por feed RSS XML
    channel_id = settings.youtube_channel_id
    if payload and payload.channel_url:
        match = re.search(r"channel/(UC[\w-]+)", payload.channel_url)
        if match:
            channel_id = match.group(1)
        else:
            channel_id = payload.channel_url.strip()

    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url)
            if r.status_code != 200:
                raise HTTPException(status_code=400, detail="No se pudo leer el feed del canal de YouTube.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error conectando con YouTube: {e}")
            
    root = ET.fromstring(r.text)
    ns = {'atom': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015'}
    
    added_count = 0
    for entry in root.findall('atom:entry', ns):
        video_id_el = entry.find('yt:videoId', ns)
        title_el = entry.find('atom:title', ns)
        if video_id_el is None or title_el is None:
            continue
        
        video_id = video_id_el.text
        title = title_el.text
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        
        # Comprobar si existe
        result = await session.execute(select(Document).where(Document.file_path == video_url))
        existe = result.scalar_one_or_none()
        if not existe:
            new_id = uuid.uuid4()
            nuevo_doc = Document(
                id=new_id,
                filename=title,
                file_path=video_url,
                document_type="youtube",
                status=DocumentStatus.PENDING
            )
            session.add(nuevo_doc)
            await session.flush()
            
            process_youtube_video_task.delay(str(new_id))
            added_count += 1

    return {"status": "success", "message": f"Se han encolado {added_count} nuevos vídeos.", "added": added_count}

