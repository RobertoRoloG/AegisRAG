import os
import sys
import uuid
import yt_dlp

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.postgres import sync_session_factory
from app.db.models import Document, DocumentStatus
from app.workers.ingestion import process_youtube_video_task
from app.core.config import get_settings

settings = get_settings()

def scrape_and_enqueue_channel_videos():
    channel_id = settings.youtube_channel_id
    url = f"https://www.youtube.com/channel/{channel_id}/videos"
    
    print(f"[+] Conectando y extrayendo vídeos del canal mediante yt-dlp: {channel_id}...")
    
    # Configurar opciones de yt-dlp para extraer metadatos sin descargar
    ydl_opts = {
        'extract_flat': True,
        'skip_download': True,
        'quiet': True,
        'no_warnings': True,
    }
    
    # Comprobar si existe archivo de cookies para pasárselo a yt-dlp si fuera necesario
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cookies_file = os.path.join(backend_dir, "youtube_cookies.txt")
    if not os.path.exists(cookies_file):
        cookies_file = os.path.join(backend_dir, "cookies.txt")
        
    if os.path.exists(cookies_file):
        print(f"[+] Usando cookies para la extracción: {cookies_file}")
        ydl_opts['cookiefile'] = cookies_file
        
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(url, download=False)
            
        if 'entries' not in result or not result['entries']:
            print("[-] No se encontraron vídeos o el canal está vacío.")
            return
            
        entries = result['entries']
        print(f"[+] Se han extraído {len(entries)} vídeos del canal.")
        
    except Exception as e:
        print(f"[-] Error al extraer información del canal con yt-dlp: {e}")
        return
        
    added_count = 0
    with sync_session_factory() as session:
        for entry in entries:
            video_id = entry.get('id')
            title = entry.get('title', f"Vídeo {video_id}")
            
            if not video_id:
                continue
                
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            
            # Comprobar si ya existe en la base de datos
            existe = session.query(Document).filter(Document.file_path == video_url).first()
            if existe:
                print(f"[-] Omitiendo {video_id} (Ya existe: {existe.filename} - Estado: {existe.status})")
                continue
                
            new_id = uuid.uuid4()
            nuevo_doc = Document(
                id=new_id,
                filename=title,
                file_path=video_url,
                document_type="youtube",
                status=DocumentStatus.PENDING
            )
            session.add(nuevo_doc)
            session.commit()
            
            # Encolar la tarea asíncrona de indexación en Celery
            process_youtube_video_task.delay(str(new_id))
            print(f"[+] Encolado con éxito: '{title}' (ID: {video_id})")
            added_count += 1
            
    print(f"\n[+] Proceso finalizado. Se han añadido {added_count} nuevos vídeos a la cola de Celery.")

if __name__ == "__main__":
    scrape_and_enqueue_channel_videos()
