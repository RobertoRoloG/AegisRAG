import os
import sys

# Agregar el directorio raíz de la aplicación al path de importación
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.postgres import sync_session_factory
from app.db.models import Document, DocumentStatus
from app.workers.ingestion import process_pdf_task, process_youtube_video_task

def requeue_stuck_documents():
    print("Buscando documentos atascados en estado PROCESSING o PENDING...")
    with sync_session_factory() as session:
        # Buscar todos los documentos en PROCESSING
        stuck_docs = session.query(Document).filter(
            Document.status.in_([DocumentStatus.PROCESSING, DocumentStatus.PENDING])
        ).all()
        
        if not stuck_docs:
            print("No hay documentos atascados en PROCESSING o PENDING.")
            return
            
        print(f"Encontrados {len(stuck_docs)} documentos atascados:")
        for doc in stuck_docs:
            print(f"- [{doc.document_type}] {doc.filename} (ID: {doc.id}, Estado: {doc.status})")
            
            # Resetear estado a PENDING para que el flujo sea limpio
            doc.status = DocumentStatus.PENDING
            doc.error_message = None
            session.commit()
            
            # Reencolar en Celery
            if doc.document_type == "youtube":
                print(f"  Encolando tarea de vídeo de YouTube para {doc.filename}...")
                process_youtube_video_task.delay(str(doc.id))
            else:
                print(f"  Encolando tarea de PDF para {doc.filename}...")
                process_pdf_task.delay(str(doc.id))
                
        print("Todos los documentos atascados han sido reencolados con éxito.")

if __name__ == "__main__":
    requeue_stuck_documents()
