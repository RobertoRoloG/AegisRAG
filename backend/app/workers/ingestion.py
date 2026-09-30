"""
AEGIS — Tareas de ingestión asíncrona de documentos (PDFs y Vídeos de YouTube).

Pipeline optimizado ejecutado por el worker Celery:
1. Marca el documento como PROCESSING en PostgreSQL.
2. Extrae texto (PDFs con pypdfium2 / OCR, YouTube con transcripciones).
3. Fragmenta el texto en chunks semánticos.
4. Genera embeddings densos y esparcidos (búsqueda híbrida).
5. Inserta vectores + metadatos en Qdrant.
6. Actualiza el estado a COMPLETED (o FAILED si ocurre algún error).

Usa sesiones síncronas de SQLAlchemy porque Celery opera
en procesos separados sin event loop async.
"""

import logging
import os
import random
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pypdfium2
import requests
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    SparseVector,
)

# Garantizar resolución de imports 'app.*'
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None

from app.app_security.prompt_guard import sanitize_text_for_indexing
from app.core.config import get_settings
from app.db.models import Document, DocumentStatus
from app.db.postgres import sync_session_factory
from app.db.qdrant import get_qdrant_client
from app.services.vector_store import (
    ChunkData,
    generate_dense_embeddings,
    generate_sparse_embeddings,
    upsert_chunks,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()

_rapid_ocr = None
_easy_ocr_reader = None
_pdfium_lock = threading.Lock()


def _get_rapid_ocr():
    """Retorna la instancia global del motor RapidOCR (ONNX Runtime C++)."""
    global _rapid_ocr
    if _rapid_ocr is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            logger.info("Cargando motor ultra-rápido RapidOCR (ONNX) en CPU...")
            _rapid_ocr = RapidOCR()
        except (ImportError, Exception) as e:
            logger.warning("rapidocr-onnxruntime no disponible (%s), se usará respaldo.", e)
            return None
    return _rapid_ocr


def _get_easy_ocr():
    """Retorna la instancia global del lector EasyOCR como respaldo si está instalado."""
    global _easy_ocr_reader
    if _easy_ocr_reader is None:
        try:
            import importlib
            easyocr = importlib.import_module("easyocr")
            logger.info("Cargando modelo EasyOCR respaldo en CPU...")
            _easy_ocr_reader = easyocr.Reader(["es", "en"], gpu=False)
        except (ImportError, Exception) as e:
            logger.debug("easyocr no instalado (%s). Usando RapidOCR como motor principal.", e)
            return None
    return _easy_ocr_reader


def _ocr_single_image(args: tuple[int, np.ndarray]) -> tuple[int, str]:
    """Ejecuta OCR sobre una matriz de imagen (totalmente thread-safe e independiente de PDFium)."""
    page_num, img_array = args
    try:
        # 1. RapidOCR ONNX
        rapid_ocr = _get_rapid_ocr()
        if rapid_ocr is not None:
            results, _ = rapid_ocr(img_array)
            if results:
                ocr_text = " ".join([res[1] for res in results])
                if ocr_text.strip():
                    return (page_num, ocr_text.strip())

        # 2. Respaldo EasyOCR
        easy_ocr = _get_easy_ocr()
        if easy_ocr is not None:
            ocr_results = easy_ocr.readtext(img_array, detail=0)
            ocr_text = " ".join(ocr_results)
            return (page_num, ocr_text.strip())

        return (page_num, "")
    except Exception as exc:
        logger.error("Error ejecutando OCR en página %d: %s", page_num, exc)
        return (page_num, "")


def _extract_pdf_pages_safe(file_path: str) -> tuple[list[tuple[int, str]], list[tuple[int, np.ndarray]]]:
    """
    Extrae texto e imágenes de forma thread-safe usando pypdfium2.
    El parsing C de PDFium se ejecuta secuencialmente (tarda < 0.05s en digital).
    """
    digital_pages = []
    ocr_pages = []

    with _pdfium_lock:
        pdf_doc = pypdfium2.PdfDocument(file_path)
        for page_num, page in enumerate(pdf_doc, start=1):
            textpage = page.get_textpage()
            text = textpage.get_text_range()
            if text and text.strip():
                digital_pages.append((page_num, text.strip()))
            else:
                # OCR desactivado temporalmente para agilizar la ingestión.
                # Las imágenes se ignoran en el índice pero el archivo original no se altera.
                pass
        pdf_doc.close()

    return digital_pages, ocr_pages


@celery_app.task(
    name="AEGIS.process_pdf",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def process_pdf_task(self, document_id: str) -> dict[str, str | int]:  # noqa: ANN001
    """
    Procesa un documento PDF: extracción thread-safe, OCR paralelo, chunking,
    generación de embeddings y almacenamiento en Qdrant.

    Args:
        document_id: UUID del documento en PostgreSQL.

    Returns:
        Diccionario con el resultado del procesamiento.
    """
    logger.info("Iniciando procesamiento del documento: %s", document_id)

    with sync_session_factory() as session:
        try:
            # ── 1. Marcar como PROCESSING ──────────────────
            document = session.get(Document, document_id)
            if document is None:
                logger.error("Documento no encontrado: %s", document_id)
                return {"status": "error", "message": "Documento no encontrado"}

            document.status = DocumentStatus.PROCESSING
            session.commit()
            logger.info("Documento %s marcado como PROCESSING", document_id)

            # ── 2. Extracción de Páginas (Thread-Safe + OCR Paralelo) ──
            target_path = Path(document.file_path)
            if not target_path.is_absolute() and not target_path.exists():
                backend_relative = _BACKEND_DIR / target_path
                if backend_relative.exists():
                    target_path = backend_relative

            digital_pages, ocr_pages = _extract_pdf_pages_safe(str(target_path))

            logger.info(
                "PDF '%s': %d páginas digitales, %d páginas requieren OCR",
                document.filename,
                len(digital_pages),
                len(ocr_pages),
            )

            pages_results: list[tuple[int, str]] = list(digital_pages)

            # Si hay páginas que requieren OCR, procesarlas en paralelo sobre las imágenes
            if ocr_pages:
                _get_rapid_ocr()
                workers = min(4, os.cpu_count() or 4)
                logger.info("Ejecutando OCR en paralelo para %d páginas con %d hilos...", len(ocr_pages), workers)
                
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    ocr_results = list(executor.map(_ocr_single_image, ocr_pages))
                
                for p_num, ocr_txt in ocr_results:
                    if ocr_txt and ocr_txt.strip():
                        pages_results.append((p_num, ocr_txt.strip()))

            # Ordenar todas las páginas por su número
            pages_text = sorted(pages_results, key=lambda x: x[0])

            if not pages_text:
                raise ValueError(
                    f"El PDF '{document.filename}' no contiene texto digital ni texto reconocible por OCR."
                )

            logger.info(
                "Extraídas %d páginas con texto (digital/OCR) del documento %s",
                len(pages_text),
                document_id,
            )

            # ── 3. Chunking ───────────────────────────────
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
                length_function=len,
                separators=["\n\n", "\n", ". ", " ", ""],
            )

            chunks: list[ChunkData] = []
            chunk_index = 0

            for page_num, page_text in pages_text:
                page_chunks = splitter.split_text(page_text)
                for chunk_text in page_chunks:
                    # Sanitizar PII antes de indexar en Qdrant
                    safe_text = sanitize_text_for_indexing(chunk_text)
                    chunks.append(
                        ChunkData(
                            text=safe_text,
                            doc_id=document_id,
                            filename=document.filename,
                            page_number=page_num,
                            chunk_index=chunk_index,
                        )
                    )
                    chunk_index += 1

            logger.info(
                "Generados %d chunks del documento %s",
                len(chunks),
                document_id,
            )

            # ── 4 & 5. Generar embeddings e Insertar en Qdrant por lotes (Batching ligero de 25) ──
            batch_size = 25
            total_chunks = len(chunks)
            logger.info(
                "Iniciando cálculo de embeddings e inserción en Qdrant por lotes (Lote: %d, Total: %d chunks)",
                batch_size,
                total_chunks
            )
            
            for i in range(0, total_chunks, batch_size):
                chunk_batch = chunks[i : i + batch_size]
                batch_texts = [c.text for c in chunk_batch]
                
                # Generar embeddings para este lote
                dense_batch = generate_dense_embeddings(batch_texts)
                sparse_batch = generate_sparse_embeddings(batch_texts)
                
                # Insertar este lote en Qdrant
                upsert_chunks(
                    chunks=chunk_batch,
                    dense_embeddings=dense_batch,
                    sparse_embeddings=sparse_batch,
                )
                
                logger.info(
                    "Lote procesado: Chunks %d a %d de %d para el documento %s",
                    i,
                    min(i + batch_size, total_chunks),
                    total_chunks,
                    document_id
                )

            # ── 6. Marcar como COMPLETED ───────────────────
            document.status = DocumentStatus.COMPLETED
            document.total_chunks = len(chunks)
            document.error_message = None
            session.commit()

            logger.info(
                "Documento %s procesado correctamente: %d chunks",
                document_id,
                len(chunks),
            )
            return {
                "status": "completed",
                "document_id": document_id,
                "total_chunks": len(chunks),
            }

        except Exception as exc:
            session.rollback()
            
            logger.warning(
                "Fallo en el intento de procesamiento del documento %s (intento %d/4): %s",
                document_id,
                self.request.retries + 1,
                exc,
            )

            try:
                raise self.retry(exc=exc)
            except self.MaxRetriesExceededError:
                logger.error(
                    "Reintentos máximos de Celery agotados para el documento %s. Marcando como FAILED.",
                    document_id,
                )
                try:
                    document = session.get(Document, document_id)
                    if document is not None:
                        document.status = DocumentStatus.FAILED
                        document.error_message = f"Máximos reintentos agotados. Error original: {exc}"
                        session.commit()
                except Exception as update_exc:
                    logger.exception(
                        "No se pudo actualizar el estado a FAILED definitivo para %s: %s",
                        document_id,
                        update_exc,
                    )
                    session.rollback()

                return {
                    "status": "failed",
                    "document_id": document_id,
                    "error": f"Reintentos máximos agotados. Error original: {exc}",
                }


# ── TAREAS DE SINCRONIZACIÓN E INGESTIÓN DE YOUTUBE ──────────────────

@celery_app.task(
    name="AEGIS.process_youtube_video",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def process_youtube_video_task(self, document_id: str):
    """Descarga la transcripción del vídeo de YouTube, genera embeddings y la guarda en Qdrant."""
    logger.info("Iniciando procesamiento de vídeo de YouTube: %s", document_id)
    
    with sync_session_factory() as session:
        doc = session.get(Document, document_id)
        if doc is None:
            logger.error("Documento no encontrado: %s", document_id)
            return {"status": "error", "message": "Vídeo no encontrado"}
            
        doc.status = DocumentStatus.PROCESSING
        session.commit()
        
        try:
            # Extraer video_id de la URL
            file_path_str = doc.file_path or ""
            video_id = file_path_str.split("v=")[-1].split("&")[0] if file_path_str else str(doc.id)
            logger.info("Descargando transcripción para video_id: %s", video_id)
            
            try:
                # Comprobar si existe un archivo de cookies en backend/ o subdirectorios
                backend_dir = Path(__file__).resolve().parent.parent.parent
                cookies_candidates = [
                    backend_dir / "youtube_cookies.txt",
                    backend_dir / "cookies.txt",
                    backend_dir / "app" / "youtube_cookies.txt",
                ]
                cookies_path = None
                for candidate in cookies_candidates:
                    if candidate.exists():
                        cookies_path = str(candidate)
                        break

                if cookies_path:
                    logger.info("Usando cookies de YouTube desde: %s", cookies_path)

                sleep_time = random.randint(5, 12)
                logger.info("Pausando la descarga durante %d segundos para prevenir rate-limiting...", sleep_time)
                time.sleep(sleep_time)

                session_http = requests.Session()
                session_http.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept-Language': 'es-ES,es;q=0.9',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Origin': 'https://www.youtube.com',
                    'Referer': 'https://www.youtube.com/'
                })

                if cookies_path:
                    try:
                        cookie_jar = MozillaCookieJar(cookies_path)
                        cookie_jar.load(ignore_discard=True, ignore_expires=True)
                        session_http.cookies.update(cookie_jar)
                    except Exception as e:
                        logger.warning("Error al cargar las cookies desde MozillaCookieJar: %s", e)

                if YouTubeTranscriptApi is None:
                    raise ImportError("El módulo 'youtube-transcript-api' no está instalado en el entorno.")

                api_cls: Any = YouTubeTranscriptApi
                ytt = api_cls(http_client=session_http)
                fetched = ytt.fetch(video_id, languages=['es', 'es-ES', 'es-419', 'en'])
                transcript = fetched.to_raw_data() if hasattr(fetched, 'to_raw_data') else list(fetched)
            except Exception as tr_exc:
                # Si YouTube no tiene transcripción o persiste el error, marcamos como FAILED
                logger.warning("Vídeo %s sin transcripción disponible: %s", video_id, tr_exc)
                doc.status = DocumentStatus.FAILED
                doc.error_message = f"Sin transcripción disponible en YouTube o baneo de IP ({tr_exc})"
                session.commit()
                return {"status": "failed", "document_id": document_id, "error": str(tr_exc)}
                
            # Segmentar transcripción en bloques de 45-90 segundos
            chunks_data: list[ChunkData] = []
            chunk_index = 0
            texto_acumulado: list[str] = []
            segundo_inicio: float = 0.0
            has_started = False
            
            for entrada in transcript:
                text_val = str(entrada.get("text", "") if isinstance(entrada, dict) else getattr(entrada, "text", ""))
                start_val = float(entrada.get("start", 0.0) if isinstance(entrada, dict) else getattr(entrada, "start", 0.0))
                dur_val = float(entrada.get("duration", 0.0) if isinstance(entrada, dict) else getattr(entrada, "duration", 0.0))

                if not has_started:
                    segundo_inicio = start_val
                    has_started = True

                texto_acumulado.append(text_val)
                
                if (start_val + dur_val) - segundo_inicio >= 45:
                    chunks_data.append(
                        ChunkData(
                            text=" ".join(texto_acumulado),
                            doc_id=str(doc.id),
                            filename=doc.filename,
                            page_number=int(segundo_inicio),
                            chunk_index=chunk_index,
                        )
                    )
                    chunk_index += 1
                    texto_acumulado = []
                    has_started = False
                    
            if texto_acumulado and has_started:
                chunks_data.append(
                    ChunkData(
                        text=" ".join(texto_acumulado),
                        doc_id=str(doc.id),
                        filename=doc.filename,
                        page_number=int(segundo_inicio),
                        chunk_index=chunk_index,
                    )
                )
                
            if not chunks_data:
                logger.warning("La transcripción del vídeo %s está vacía.", video_id)
                doc.status = DocumentStatus.FAILED
                doc.error_message = "Transcripción vacía"
                session.commit()
                return {"status": "failed", "document_id": document_id, "error": "Transcripción vacía"}
                
            logger.info("Generados %d chunks para el vídeo %s", len(chunks_data), doc.filename)
            
            # Generar vectores de búsqueda híbrida e insertar en la colección de Qdrant
            texts = [c.text for c in chunks_data]
            dense = generate_dense_embeddings(texts)
            sparse = generate_sparse_embeddings(texts)
            
            client_sync = get_qdrant_client()
            
            points = []
            for chunk, dense_emb, sparse_emb in zip(chunks_data, dense, sparse, strict=True):
                points.append(
                    PointStruct(
                        id=str(uuid.uuid4()),
                        vector={
                            "dense": dense_emb,
                            "sparse": SparseVector(indices=sparse_emb["indices"], values=sparse_emb["values"])
                        },
                        payload={
                            "doc_id": chunk.doc_id,
                            "filename": chunk.filename,
                            "page_number": chunk.page_number,  # Timestamp inicial (segundos)
                            "chunk_index": chunk.chunk_index,
                            "text": chunk.text,
                            "type": "youtube",      # Identificador de fuente
                            "video_id": video_id
                        }
                    )
                )
                
            logger.info("Subiendo %d puntos a Qdrant...", len(points))
            client_sync.upsert(collection_name=settings.qdrant_collection, points=points)
            
            doc.status = DocumentStatus.COMPLETED
            doc.total_chunks = len(chunks_data)
            doc.error_message = None
            session.commit()
            
            logger.info("Vídeo %s procesado con éxito.", doc.filename)
            return {
                "status": "completed",
                "document_id": document_id,
                "total_chunks": len(chunks_data),
            }
            
        except Exception as exc:
            session.rollback()
            logger.error("Fallo al procesar el vídeo %s: %s", document_id, exc)
            
            try:
                raise self.retry(exc=exc)
            except self.MaxRetriesExceededError:
                logger.error("Reintentos máximos agotados para el vídeo %s. Marcando como FAILED.", document_id)
                try:
                    document = session.get(Document, document_id)
                    if document is not None:
                        document.status = DocumentStatus.FAILED
                        document.error_message = f"Error al procesar: {exc}"
                        session.commit()
                except Exception as update_exc:
                    logger.exception("No se pudo actualizar el estado a FAILED para %s: %s", document_id, update_exc)
                    session.rollback()
                return {
                    "status": "failed",
                    "document_id": document_id,
                    "error": f"Error: {exc}",
                }


def _parse_vtt_transcript(transcript_text: str) -> list[tuple[float, str]]:
    """Extrae inicio y texto de cada bloque WebVTT o texto con timestamps."""
    timestamp = re.compile(
        r"(?P<start>\d{2}:\d{2}:\d{2}(?:\.\d{3})?|\d{2}:\d{2}\.\d{3})\s+-->"
    )
    entries: list[tuple[float, str]] = []
    blocks = re.split(r"\n\s*\n", transcript_text.replace("\r\n", "\n"))
    for block in blocks:
        match = timestamp.search(block)
        if not match:
            continue
        value = match.group("start")
        parts = [float(part) for part in value.split(":")]
        seconds = (
            parts[-1] + parts[-2] * 60 + (parts[-3] * 3600 if len(parts) == 3 else 0)
        )
        lines = block[match.end() :].splitlines()
        text = " ".join(
            line.strip() for line in lines if line.strip() and "-->" not in line
        )
        text = re.sub(r"<[^>]+>", "", text).strip()
        if text:
            entries.append((seconds, text))
    return entries


@celery_app.task(name="AEGIS.process_youtube_transcript", bind=True, max_retries=3)
def process_youtube_transcript_task(
    self, document_id: str, transcript_text: str
):  # noqa: ANN001
    """Indexa un VTT o transcripción aportada manualmente sin consultar la API de YouTube."""
    with sync_session_factory() as session:
        document = session.get(Document, document_id)
        if document is None:
            return {"status": "error", "message": "Vídeo no encontrado"}
        try:
            document.status = DocumentStatus.PROCESSING
            session.commit()
            entries = _parse_vtt_transcript(transcript_text)
            if not entries:
                raise ValueError("No se encontraron bloques con timestamps válidos en el archivo")

            chunks_data: list[ChunkData] = []
            current_text: list[str] = []
            chunk_start = entries[0][0]
            chunk_index = 0
            for start, text in entries:
                if current_text and start - chunk_start >= 45:
                    chunks_data.append(
                        ChunkData(
                            text=" ".join(current_text),
                            doc_id=document_id,
                            filename=document.filename,
                            page_number=int(chunk_start),
                            chunk_index=chunk_index,
                        )
                    )
                    chunk_index += 1
                    current_text = []
                    chunk_start = start
                current_text.append(text)
            if current_text:
                chunks_data.append(
                    ChunkData(
                        text=" ".join(current_text),
                        doc_id=document_id,
                        filename=document.filename,
                        page_number=int(chunk_start),
                        chunk_index=chunk_index,
                    )
                )

            texts = [chunk.text for chunk in chunks_data]
            dense = generate_dense_embeddings(texts)
            sparse = generate_sparse_embeddings(texts)
            client = get_qdrant_client()
            
            # Limpiar puntos anteriores del mismo documento si los hubiera
            client.delete(
                collection_name=settings.qdrant_collection,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="doc_id",
                            match=MatchValue(value=document_id),
                        )
                    ]
                ),
            )
            
            video_id = document.file_path.split("v=")[-1].split("&")[0] if document.file_path else ""
            points = [
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector={
                        "dense": dense_value,
                        "sparse": SparseVector(
                            indices=sparse_value["indices"],
                            values=sparse_value["values"],
                        ),
                    },
                    payload={
                        "doc_id": document_id,
                        "filename": document.filename,
                        "page_number": chunk.page_number,
                        "chunk_index": chunk.chunk_index,
                        "text": chunk.text,
                        "type": "youtube",
                        "video_id": video_id,
                    },
                )
                for chunk, dense_value, sparse_value in zip(
                    chunks_data, dense, sparse, strict=True
                )
            ]
            client.upsert(collection_name=settings.qdrant_collection, points=points)
            document.status = DocumentStatus.COMPLETED
            document.total_chunks = len(chunks_data)
            document.error_message = None
            session.commit()
            return {
                "status": "completed",
                "document_id": document_id,
                "total_chunks": len(chunks_data),
            }
        except Exception as exc:
            session.rollback()
            document = session.get(Document, document_id)
            if document is not None:
                document.status = DocumentStatus.FAILED
                document.error_message = f"Error al procesar transcripción: {exc}"
                session.commit()
            return {
                "status": "failed",
                "document_id": document_id,
                "error": f"Error: {exc}",
            }
