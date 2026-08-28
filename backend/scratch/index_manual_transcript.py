import os
import re
import sys
import uuid
from qdrant_client.models import PointStruct, SparseVector

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.postgres import sync_session_factory
from app.db.models import Document, DocumentStatus
from app.services.vector_store import (
    ChunkData,
    generate_dense_embeddings,
    generate_sparse_embeddings,
    get_qdrant_client,
)
from app.core.config import get_settings

settings = get_settings()

def parse_transcript(raw_text):
    lines = [line.strip() for line in raw_text.strip().split("\n") if line.strip()]
    parsed_entries = []
    
    current_time = 0.0
    time_regex = re.compile(r"^(\d+):(\d{2})$")
    
    for i, line in enumerate(lines):
        match = time_regex.match(line)
        if match:
            mins, secs = map(int, match.groups())
            current_time = float(mins * 60 + secs)
        else:
            # Si es texto, asociarlo al último tiempo detectado
            parsed_entries.append({"text": line, "start": current_time, "duration": 3.0})
            
    return parsed_entries

def index_manual_video(document_id, raw_text):
    print(f"Iniciando indexación manual del documento: {document_id}")
    entries = parse_transcript(raw_text)
    if not entries:
        print("[-] No se encontraron entradas válidas de texto.")
        return
        
    with sync_session_factory() as session:
        doc = session.get(Document, document_id)
        if not doc:
            print("[-] Documento no encontrado.")
            return
            
        doc.status = DocumentStatus.PROCESSING
        session.commit()
        
        # Agrupar en bloques de 90 segundos
        chunks_data = []
        chunk_index = 0
        texto_acumulado = []
        segundo_inicio = None
        
        for entrada in entries:
            text_val = entrada["text"]
            start_val = entrada["start"]
            
            if segundo_inicio is None:
                segundo_inicio = start_val
            texto_acumulado.append(text_val)
            
            if (start_val - segundo_inicio) >= 90:
                chunks_data.append(ChunkData(
                    text=" ".join(texto_acumulado),
                    doc_id=str(doc.id),
                    filename=doc.filename,
                    page_number=int(segundo_inicio),
                    chunk_index=chunk_index
                ))
                chunk_index += 1
                texto_acumulado = []
                segundo_inicio = None
                
        if texto_acumulado and segundo_inicio is not None:
            chunks_data.append(ChunkData(
                text=" ".join(texto_acumulado),
                doc_id=str(doc.id),
                filename=doc.filename,
                page_number=int(segundo_inicio),
                chunk_index=chunk_index
            ))
            
        # Generar embeddings locales
        texts = [c.text for c in chunks_data]
        dense = generate_dense_embeddings(texts)
        sparse = generate_sparse_embeddings(texts)
        
        # Subir a Qdrant
        client = get_qdrant_client()
        video_id = doc.file_path.split("v=")[-1].split("&")[0]
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
            
        client.upsert(collection_name=settings.qdrant_collection, points=points)
        
        doc.status = DocumentStatus.COMPLETED
        doc.total_chunks = len(chunks_data)
        doc.error_message = None
        session.commit()
        print(f"[+] Indexado con éxito: {len(chunks_data)} chunks.")
