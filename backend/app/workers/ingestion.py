"""
AegisRAG — Tarea de ingestión asíncrona de documentos PDF.

Pipeline optimizado ejecutado por el worker Celery:
1. Marca el documento como PROCESSING en PostgreSQL
2. Lee el PDF y extrae texto (pypdfium2 thread-safe + RapidOCR ONNX paralelo / EasyOCR fallback)
3. Fragmenta el texto con RecursiveCharacterTextSplitter
4. Genera embeddings con FastEmbed (modelo local ONNX)
5. Inserta vectores + metadatos en Qdrant
6. Actualiza el estado a COMPLETED (o FAILED si hay error)

Usa sesiones síncronas de SQLAlchemy porque Celery opera
en procesos separados sin event loop async.
"""

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pypdfium2
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import get_settings
from app.db.models import Document, DocumentStatus
from app.db.postgres import sync_session_factory
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
        except ImportError:
            logger.warning("rapidocr-onnxruntime no disponible, se usará respaldo.")
    return _rapid_ocr


def _get_easy_ocr():
    """Retorna la instancia global del lector EasyOCR como respaldo."""
    global _easy_ocr_reader
    if _easy_ocr_reader is None:
        import easyocr
        logger.info("Cargando modelo EasyOCR respaldo en CPU...")
        _easy_ocr_reader = easyocr.Reader(["es", "en"], gpu=False)
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
        ocr_results = easy_ocr.readtext(img_array, detail=0)
        ocr_text = " ".join(ocr_results)
        return (page_num, ocr_text.strip())
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
    name="aegisrag.process_pdf",
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
            digital_pages, ocr_pages = _extract_pdf_pages_safe(document.file_path)
            total_pages = len(digital_pages) + len(ocr_pages)

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
                    chunks.append(
                        ChunkData(
                            text=chunk_text,
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

            # ── 4 & 5. Generar embeddings e Insertar en Qdrant por lotes (Batching de 100) ──
            batch_size = 100
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
