"""
AEGIS - Script de Sincronizacion Directa de Videos de YouTube desde PC Local.

Este script se ejecuta localmente en tu PC (usando tu IP residencial)
para extraer la lista completa de videos del canal, descargar sus transcripciones,
generar embeddings locales y sincronizar los datos directamente en la base de datos de la VPS.

Usa cookies del navegador Brave para autenticarse ante YouTube y evitar bloqueos.
"""

import os
import sys
import uuid
import time
import random
import logging
import tempfile
import glob
from pathlib import Path

# Ajustar sys.path para importar modulos de la aplicacion
backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

import yt_dlp
import webvtt
from youtube_transcript_api import YouTubeTranscriptApi
import requests
from http.cookiejar import MozillaCookieJar
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, SparseVector

from app.db.models import Document, DocumentStatus
from app.services.vector_store import generate_dense_embeddings, generate_sparse_embeddings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
# Force UTF-8 output on Windows
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

logger = logging.getLogger("sync_from_pc")

# -- CONFIGURACION (Por defecto lee variables de entorno o valores estándar) --
VPS_IP = os.getenv("VPS_IP", "127.0.0.1")
POSTGRES_URI = os.getenv("POSTGRES_SYNC_URI", f"postgresql://aegisrag:aegisrag_secret@{VPS_IP}:5433/aegisrag")
QDRANT_URL = os.getenv("QDRANT_URL", f"http://{VPS_IP}:6333")
CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "UCoZWQl3d034u8OIqnEGEnXA")
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "aegis_chunks")

# Navegador a usar para cookies (brave funciona sin permisos de admin)
BROWSER_FOR_COOKIES = "brave"

# Delay entre videos para evitar rate-limit (segundos)
MIN_DELAY = 30
MAX_DELAY = 60

# Reintentos con backoff exponencial
MAX_RETRIES = 3
INITIAL_BACKOFF = 60  # 1 minuto de espera base al recibir 429

engine = create_engine(POSTGRES_URI)
SyncSession = sessionmaker(bind=engine)
qdrant_client = QdrantClient(url=QDRANT_URL)


class ChunkData:
    def __init__(self, text: str, doc_id: str, filename: str, page_number: int, chunk_index: int):
        self.text = text
        self.doc_id = doc_id
        self.filename = filename
        self.page_number = page_number
        self.chunk_index = chunk_index


def fetch_channel_videos() -> list[dict]:
    """Obtiene la lista de todos los videos del canal usando yt-dlp con cookies de Brave."""
    channel_url = f"https://www.youtube.com/channel/{CHANNEL_ID}/videos"
    logger.info(f"Conectando a YouTube con cookies de {BROWSER_FOR_COOKIES} para listar videos del canal...")

    ydl_opts = {
        'extract_flat': True,
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
        'cookiesfrombrowser': (BROWSER_FOR_COOKIES,),
    }

    # Tambien podemos usar cookiefile como alternativa
    cookies_file = backend_dir / "youtube_cookies.txt"
    if cookies_file.exists():
        ydl_opts['cookiefile'] = str(cookies_file)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        res = ydl.extract_info(channel_url, download=False)
        entries = res.get('entries', [])

    logger.info(f"Se han encontrado {len(entries)} videos en el canal.")
    return entries


def get_video_transcript(video_id: str, attempt: int = 1) -> list[dict]:
    """
    Obtiene la transcripcion de un video de YouTube.
    Intenta primero con YouTubeTranscriptApi, luego fallback a yt-dlp.
    Incluye backoff exponencial ante errores 429.
    """
    transcript = []

    # -- Intento 1: YouTubeTranscriptApi con cookies de archivo --
    try:
        session_http = requests.Session()
        session_http.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
        })

        cookies_file = backend_dir / "youtube_cookies.txt"
        if cookies_file.exists():
            try:
                with open(cookies_file, "r", encoding="utf-8") as f:
                    c_txt = f.read().replace("#HttpOnly_", "")
                tmp_c_file = backend_dir / "tmp_cookies.txt"
                with open(tmp_c_file, "w", encoding="utf-8") as f:
                    f.write(c_txt)
                cookie_jar = MozillaCookieJar(str(tmp_c_file))
                cookie_jar.load(ignore_discard=True, ignore_expires=True)
                session_http.cookies = cookie_jar
                if tmp_c_file.exists():
                    os.remove(tmp_c_file)
            except Exception as e_c:
                logger.warning(f"No se pudieron cargar cookies para {video_id}: {e_c}")

        ytt = YouTubeTranscriptApi(http_client=session_http)
        raw_tx = ytt.fetch(video_id, languages=['es', 'es-ES', 'es-419', 'en'])
        for item in raw_tx:
            t_val = getattr(item, 'text', None) or (item.get('text') if isinstance(item, dict) else str(item))
            s_val = getattr(item, 'start', None) if hasattr(item, 'start') else (item.get('start') if isinstance(item, dict) else 0.0)
            d_val = getattr(item, 'duration', None) if hasattr(item, 'duration') else (item.get('duration') if isinstance(item, dict) else 0.0)
            if t_val:
                transcript.append({'text': t_val, 'start': s_val, 'duration': d_val})
        if transcript:
            logger.info(f"Transcripcion obtenida via YouTubeTranscriptApi ({len(transcript)} lineas).")
            return transcript
    except Exception as e_ytt:
        logger.warning(f"YouTubeTranscriptApi fallo para {video_id}: {e_ytt}")

    # -- Intento 2: yt-dlp subtitulos con cookies de navegador Brave --
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts = {
                'skip_download': True,
                'writesubtitles': True,
                'writeautomaticsub': True,
                'subtitleslangs': ['es-orig', 'es.*', 'es', 'es-419', 'es-ES', 'en.*', 'en'],
                'outtmpl': os.path.join(tmpdir, '%(id)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'ignoreerrors': True,
                'cookiesfrombrowser': (BROWSER_FOR_COOKIES,),
            }

            # Tambien agregar cookiefile como respaldo
            cookies_file = backend_dir / "youtube_cookies.txt"
            if cookies_file.exists():
                ydl_opts['cookiefile'] = str(cookies_file)

            video_url = f"https://www.youtube.com/watch?v={video_id}"
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])

            vtt_files = glob.glob(os.path.join(tmpdir, f"{video_id}*.vtt"))
            if vtt_files:
                for caption in webvtt.read(vtt_files[0]):
                    parts = caption.start.split(':')
                    if len(parts) == 3:
                        start_sec = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                    elif len(parts) == 2:
                        start_sec = int(parts[0]) * 60 + float(parts[1])
                    else:
                        start_sec = 0.0

                    end_parts = caption.end.split(':')
                    if len(end_parts) == 3:
                        end_sec = int(end_parts[0]) * 3600 + int(end_parts[1]) * 60 + float(end_parts[2])
                    elif len(end_parts) == 2:
                        end_sec = int(end_parts[0]) * 60 + float(end_parts[1])
                    else:
                        end_sec = start_sec + 2.0

                    duration = end_sec - start_sec
                    text = " ".join(caption.text.replace('<c>', '').replace('</c>', '').split())
                    if text:
                        transcript.append({'text': text, 'start': start_sec, 'duration': duration})

                if transcript:
                    logger.info(f"Transcripcion obtenida via yt-dlp ({len(transcript)} lineas).")
                    return transcript
    except Exception as e_vtt:
        error_str = str(e_vtt)
        if "429" in error_str and attempt <= MAX_RETRIES:
            wait_time = INITIAL_BACKOFF * (2 ** (attempt - 1))
            logger.warning(f"Rate-limit 429 detectado para {video_id}. Esperando {wait_time}s antes de reintentar (intento {attempt}/{MAX_RETRIES})...")
            time.sleep(wait_time)
            return get_video_transcript(video_id, attempt + 1)
        logger.warning(f"yt-dlp fallo para {video_id}: {e_vtt}")

    return transcript


def process_and_index_video(session, video_entry: dict) -> bool:
    """Procesa un video: descarga transcripcion, genera embeddings y sube a VPS."""
    video_id = video_entry.get('id')
    title = video_entry.get('title', f"Video {video_id}")
    video_url = f"https://www.youtube.com/watch?v={video_id}"

    # Comprobar si ya esta indexado como COMPLETED
    doc = session.query(Document).filter(Document.file_path == video_url).first()
    if doc and doc.status == DocumentStatus.COMPLETED:
        logger.info(f"Omitiendo '{title}' (ya indexado previamente como COMPLETED).")
        return True

    if not doc:
        doc_id = str(uuid.uuid4())
        doc = Document(
            id=doc_id,
            filename=title,
            file_path=video_url,
            document_type="youtube",
            status=DocumentStatus.PROCESSING
        )
        session.add(doc)
        session.commit()
    else:
        doc_id = str(doc.id)
        doc.status = DocumentStatus.PROCESSING
        doc.error_message = None
        session.commit()

    logger.info(f"Procesando video: '{title}' ({video_id})...")

    raw_transcript = get_video_transcript(video_id)
    if not raw_transcript:
        logger.warning(f"No se pudo obtener la transcripcion para '{title}'. Marcando como FAILED.")
        doc.status = DocumentStatus.FAILED
        doc.error_message = "Sin transcripcion disponible"
        session.commit()
        return False

    # Segmentar transcripcion en bloques de 90 segundos
    chunks_data = []
    chunk_index = 0
    texto_acumulado = []
    segundo_inicio = None

    for entrada in raw_transcript:
        text_val = entrada['text']
        start_val = entrada['start']
        dur_val = entrada['duration']

        if segundo_inicio is None:
            segundo_inicio = start_val
        texto_acumulado.append(text_val)

        duracion = (start_val + dur_val) - segundo_inicio
        if duracion >= 45:
            text_content = " ".join(texto_acumulado)
            chunks_data.append(ChunkData(
                text=text_content,
                doc_id=doc_id,
                filename=title,
                page_number=int(segundo_inicio),
                chunk_index=chunk_index
            ))
            chunk_index += 1
            texto_acumulado = []
            segundo_inicio = None

    if texto_acumulado and segundo_inicio is not None:
        text_content = " ".join(texto_acumulado)
        chunks_data.append(ChunkData(
            text=text_content,
            doc_id=doc_id,
            filename=title,
            page_number=int(segundo_inicio),
            chunk_index=chunk_index
        ))

    if not chunks_data:
        logger.warning(f"Transcripcion vacia para '{title}'. Marcando como FAILED.")
        doc.status = DocumentStatus.FAILED
        doc.error_message = "Transcripcion vacia"
        session.commit()
        return False

    logger.info(f"Generados {len(chunks_data)} chunks. Calculando embeddings...")
    texts = [c.text for c in chunks_data]
    dense = generate_dense_embeddings(texts)
    sparse = generate_sparse_embeddings(texts)

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
                    "page_number": chunk.page_number,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "type": "youtube",
                    "video_id": video_id
                }
            )
        )

    logger.info(f"Insertando {len(points)} puntos en Qdrant (VPS)...")
    qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points)

    doc.status = DocumentStatus.COMPLETED
    doc.total_chunks = len(chunks_data)
    doc.error_message = None
    session.commit()
    logger.info(f"[OK] Video '{title}' indexado con EXITO ({len(chunks_data)} chunks).")
    return True


def main():
    logger.info("==================================================")
    logger.info("   AEGIS -- Sincronizador YouTube PC -> VPS")
    logger.info(f"   Navegador para cookies: {BROWSER_FOR_COOKIES}")
    logger.info(f"   Delay entre videos: {MIN_DELAY}-{MAX_DELAY}s")
    logger.info("==================================================")

    entries = fetch_channel_videos()
    if not entries:
        logger.error("No se encontraron videos. Abortando.")
        return

    with SyncSession() as session:
        success_count = 0
        fail_count = 0
        skip_count = 0

        for i, entry in enumerate(entries, 1):
            logger.info(f"\n--- Video {i}/{len(entries)} ---")
            try:
                ok = process_and_index_video(session, entry)
                if ok:
                    # Check if it was a skip (already indexed)
                    video_url = f"https://www.youtube.com/watch?v={entry.get('id')}"
                    doc = session.query(Document).filter(Document.file_path == video_url).first()
                    if doc and doc.status == DocumentStatus.COMPLETED and doc.total_chunks and doc.total_chunks > 0:
                        success_count += 1
                    else:
                        skip_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                logger.error(f"Error inesperado procesando video {entry.get('id', '???')}: {e}")
                fail_count += 1

            # Pausa entre videos para evitar rate-limit
            if i < len(entries):
                delay = random.randint(MIN_DELAY, MAX_DELAY)
                logger.info(f"Pausa de {delay}s antes del siguiente video...")
                time.sleep(delay)

        logger.info("\n==================================================")
        logger.info(f"RESUMEN FINAL: {success_count} indexados, {fail_count} fallidos, {skip_count} omitidos")
        logger.info("==================================================")

if __name__ == "__main__":
    main()
