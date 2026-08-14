"""
AegisRAG — Servicio de Búsqueda Híbrida y Recuperación.

Ejecuta búsquedas combinadas (densa + esparsa) en Qdrant
y aplica Reciprocal Rank Fusion (RRF) de forma nativa en la base de datos
para obtener los candidatos más relevantes.
"""

import asyncio
import logging

from qdrant_client import models

from app.core.config import get_settings
from app.db.qdrant import get_async_qdrant_client
from app.services.vector_store import (
    generate_dense_embeddings,
    generate_sparse_embeddings,
)

logger = logging.getLogger(__name__)
settings = get_settings()


async def hybrid_search(
    query: str, 
    document_ids: list[str] | None = None, 
    top_k: int = 30
) -> list[dict]:
    """
    Ejecuta una búsqueda híbrida nativa en Qdrant con fusión RRF de forma asíncrona.

    Args:
        query: Consulta del usuario en lenguaje natural.
        document_ids: Opcional, lista de IDs de documentos para filtrar el contexto.
        top_k: Número de candidatos a recuperar antes del re-ranking.

    Returns:
        Lista de fragmentos en formato diccionario con su payload y score de fusión.
    """
    client = get_async_qdrant_client()
    collection_name = settings.qdrant_collection

    logger.info(
        "Búsqueda híbrida en colección '%s'. Query: '%s' (filter_docs=%s)",
        collection_name,
        query,
        document_ids,
    )

    # ── 1. Generar vectores de la consulta ─────────────────
    # Generar vector denso de forma no bloqueante (CPU/I/O local en hilo)
    dense_vector_list = await asyncio.to_thread(generate_dense_embeddings, [query])
    dense_vector = dense_vector_list[0]
    
    # Generar vector esparso de forma no bloqueante (CPU/I/O local en hilo)
    sparse_emb_list = await asyncio.to_thread(generate_sparse_embeddings, [query])
    sparse_emb = sparse_emb_list[0]
    sparse_vector = models.SparseVector(
        indices=sparse_emb["indices"],
        values=sparse_emb["values"]
    )

    # ── 2. Configurar filtros opcionales ───────────────────
    filter_cond = None
    if document_ids:
        filter_cond = models.Filter(
            must=[
                models.FieldCondition(
                    key="doc_id",
                    match=models.MatchAny(any=document_ids)
                )
            ]
        )

    # ── 3. Ejecutar consulta híbrida con fusión RRF ────────
    # Usamos query_points con prefetch para recuperar por ambos caminos
    # y FusionQuery para unificarlos en la base de datos de manera asíncrona.
    try:
        response = await client.query_points(
            collection_name=collection_name,
            prefetch=[
                # Búsqueda Densa (Semántica)
                models.Prefetch(
                    query=dense_vector,
                    using="dense",
                    limit=top_k,
                    filter=filter_cond,
                ),
                # Búsqueda Esparsa (Keywords / SPLADE)
                models.Prefetch(
                    query=sparse_vector,
                    using="sparse",
                    limit=top_k,
                    filter=filter_cond,
                ),
            ],
            # Fusión por Reciprocal Rank Fusion (RRF)
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=top_k,
        )
    except Exception as exc:
        logger.error("Fallo al ejecutar búsqueda híbrida en Qdrant: %s", exc)
        raise

    # ── 4. Formatear resultados ────────────────────────────
    results = []
    for point in response.points:
        payload = point.payload or {}
        results.append({
            "id": point.id,
            "score": point.score,  # Score de RRF
            "text": payload.get("text", ""),
            "doc_id": payload.get("doc_id", ""),
            "filename": payload.get("filename", ""),
            "page_number": payload.get("page_number", 0),
            "chunk_index": payload.get("chunk_index", 0),
        })

    logger.info(
        "Búsqueda híbrida completada. Recuperados %d candidatos.",
        len(results)
    )
    return results

