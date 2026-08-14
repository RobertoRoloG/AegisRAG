"""
AegisRAG — Servicio de Vector Store (Qdrant + Embeddings Híbridos).

Gestiona la colección de vectores en Qdrant (búsqueda híbrida: densa + esparsa)
y la generación de embeddings locales usando FastEmbed.

Responsabilidades:
- Crear/verificar la colección híbrida 'aegis_chunks' en Qdrant.
- Generar embeddings densos (BAAI/bge-small-en-v1.5).
- Generar embeddings esparcidos (prithivida/Splade_PP_en_v1).
- Insertar chunks con vectores (densos y esparcidos) y metadatos en Qdrant.
"""

import logging
import os
import uuid
from dataclasses import dataclass

from fastembed import TextEmbedding, SparseTextEmbedding
from qdrant_client.models import (
    Distance, 
    PointStruct, 
    VectorParams, 
    SparseVectorParams, 
    SparseIndexParams,
    SparseVector
)

from app.core.config import get_settings
from app.db.qdrant import get_qdrant_client

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Modelos de embeddings (singletons a nivel de módulo) ─────
_dense_model: TextEmbedding | None = None
_sparse_model: SparseTextEmbedding | None = None


def _get_dense_model() -> TextEmbedding:
    """Retorna la instancia singleton del modelo de embeddings densos."""
    global _dense_model
    if _dense_model is None:
        cpu_threads = os.cpu_count() or 4
        logger.info("Cargando modelo denso: %s (hilos: %d)", settings.embedding_model, cpu_threads)
        _dense_model = TextEmbedding(model_name=settings.embedding_model, threads=cpu_threads)
    return _dense_model


def _get_sparse_model() -> SparseTextEmbedding:
    """Retorna la instancia singleton del modelo de embeddings esparcidos (SPLADE)."""
    global _sparse_model
    if _sparse_model is None:
        cpu_threads = os.cpu_count() or 4
        logger.info("Cargando modelo esparso: %s (hilos: %d)", settings.sparse_embedding_model, cpu_threads)
        _sparse_model = SparseTextEmbedding(model_name=settings.sparse_embedding_model, threads=cpu_threads)
    return _sparse_model


@dataclass
class ChunkData:
    """Estructura de datos para un chunk listo para insertar en Qdrant."""
    text: str
    doc_id: str
    filename: str
    page_number: int
    chunk_index: int


def ensure_collection() -> None:
    """
    Crea la colección 'aegis_chunks' en Qdrant si no existe.
    Si existe pero no soporta vectores esparcidos, se elimina y se recrea.
    Configura:
      - Vector denso ("dense"): dim=384, Distance.COSINE
      - Vector esparso ("sparse"): SparseVectorParams
    """
    client = get_qdrant_client()
    collection_name = settings.qdrant_collection

    # Verificar si la colección existe
    collections = client.get_collections().collections
    existing = [c.name for c in collections]

    recreate = False
    if collection_name in existing:
        # Verificar la estructura actual de la colección
        info = client.get_collection(collection_name)
        # Si no tiene configuración de vectores nombrados (que es el caso de la Fase 2)
        # o si le falta el vector "sparse", marcamos para recrear.
        vectors_config = info.config.params.vectors
        sparse_config = info.config.params.sparse_vectors
        
        has_dense_named = isinstance(vectors_config, dict) and "dense" in vectors_config
        has_sparse = sparse_config is not None and "sparse" in sparse_config

        if not (has_dense_named and has_sparse):
            logger.warning(
                "La colección '%s' existente no soporta búsqueda híbrida. "
                "Se procederá a eliminarla y recrearla.",
                collection_name,
            )
            recreate = True

    if recreate:
        client.delete_collection(collection_name)
        logger.info("Colección vieja '%s' eliminada.", collection_name)

    if collection_name not in existing or recreate:
        client.create_collection(
            collection_name=collection_name,
            vectors_config={
                "dense": VectorParams(
                    size=settings.embedding_dim,
                    distance=Distance.COSINE,
                )
            },
            sparse_vectors_config={
                "sparse": SparseVectorParams(
                    index=SparseIndexParams(on_disk=True)
                )
            },
        )
        logger.info(
            "Colección híbrida '%s' creada en Qdrant (dense_dim=%d, sparse=on_disk)",
            collection_name,
            settings.embedding_dim,
        )
    else:
        logger.info(
            "Colección híbrida '%s' ya existe en Qdrant — omitiendo creación",
            collection_name,
        )


def generate_dense_embeddings(texts: list[str]) -> list[list[float]]:
    """Genera embeddings densos para una lista de textos."""
    model = _get_dense_model()
    embeddings = list(model.embed(texts))
    return [emb.tolist() for emb in embeddings]


def generate_sparse_embeddings(texts: list[str]) -> list[dict[str, list]]:
    """
    Genera embeddings esparcidos (SPLADE) para una lista de textos.
    Retorna una lista de diccionarios con formato {"indices": list[int], "values": list[float]}.
    """
    model = _get_sparse_model()
    embeddings = list(model.embed(texts))
    
    # Cada embedding es un objeto SparseEmbedding con .indices y .values
    result = []
    for emb in embeddings:
        result.append({
            "indices": emb.indices.tolist(),
            "values": emb.values.tolist(),
        })
    return result


def upsert_chunks(
    chunks: list[ChunkData], 
    dense_embeddings: list[list[float]] | None = None,
    sparse_embeddings: list[dict[str, list]] | None = None
) -> int:
    """
    Inserta chunks con sus vectores (densos y esparcidos) y metadatos en Qdrant.
    Si los embeddings no se proveen, se calculan automáticamente.
    """
    client = get_qdrant_client()
    collection_name = settings.qdrant_collection
    texts = [c.text for c in chunks]

    # Calcular embeddings densos si no se proveen
    if dense_embeddings is None:
        logger.info("Calculando embeddings densos de forma automática...")
        dense_embeddings = generate_dense_embeddings(texts)

    # Calcular embeddings esparcidos si no se proveen
    if sparse_embeddings is None:
        logger.info("Calculando embeddings esparcidos (SPLADE) de forma automática...")
        sparse_embeddings = generate_sparse_embeddings(texts)

    if len(chunks) != len(dense_embeddings) or len(chunks) != len(sparse_embeddings):
        raise ValueError(
            f"Mismatch en dimensiones: {len(chunks)} chunks, "
            f"{len(dense_embeddings)} densos, {len(sparse_embeddings)} esparcidos."
        )

    # Construir los puntos con estructura multi-vector
    points = []
    for chunk, dense_emb, sparse_emb in zip(chunks, dense_embeddings, sparse_embeddings, strict=True):
        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector={
                    "dense": dense_emb,
                    "sparse": SparseVector(
                        indices=sparse_emb["indices"],
                        values=sparse_emb["values"]
                    ),
                },
                payload={
                    "doc_id": chunk.doc_id,
                    "filename": chunk.filename,
                    "page_number": chunk.page_number,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                },
            )
        )

    # Upsert en batches de 100 puntos
    batch_size = 100
    for i in range(0, len(points), batch_size):
        batch = points[i : i + batch_size]
        client.upsert(
            collection_name=collection_name,
            points=batch,
        )

    logger.info(
        "Insertados %d chunks híbridos en la colección '%s'",
        len(points),
        collection_name,
    )
    return len(points)
