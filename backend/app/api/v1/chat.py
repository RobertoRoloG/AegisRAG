"""
AegisRAG — Controlador de Chat y Consultas.

Expone el endpoint POST /api/v1/chat/query para interactuar
con el motor de Corrective RAG (CRAG) e iniciar búsquedas
semánticas sobre los documentos indexados.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.params import Depends
from pydantic import BaseModel, Field

from app.services.crag_engine import CRAGEngine, get_crag_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["Chat"])


# ── Modelos de Petición y Respuesta ────────────────────────


class ChatQueryRequest(BaseModel):
    """Esquema de entrada para una consulta de chat."""

    query: str = Field(
        ..., 
        min_length=3, 
        max_length=1000, 
        description="Consulta del usuario a responder sobre los documentos"
    )
    document_ids: list[str] = Field(
        default_factory=list, 
        description="Lista de IDs de documentos para filtrar el contexto, si está vacía busca en todos"
    )


class SourceDocument(BaseModel):
    """Esquema de detalles de un fragmento de origen utilizado."""

    doc_id: str = Field(..., description="ID del documento en la base de datos")
    filename: str = Field(..., description="Nombre original del archivo PDF")
    page_number: int = Field(..., description="Número de página original del chunk")
    score: float = Field(..., description="Puntaje de relevancia final del Reranker")
    snippet: str = Field(..., description="Texto del fragmento de origen")


class LatencyBreakdown(BaseModel):
    """Esquema detallado de tiempos de procesamiento en milisegundos."""

    retrieval: float = Field(..., description="Tiempo en recuperar y reordenar fragmentos")
    rewrite: float = Field(..., description="Tiempo en reescribir la query (0 si no aplica)")
    generation: float = Field(..., description="Tiempo en llamada al LLM para responder")
    total: float = Field(..., description="Latencia total de extremo a extremo")


class ChatQueryResponse(BaseModel):
    """Esquema de salida final del endpoint de consulta RAG."""

    answer: str = Field(..., description="Respuesta sintetizada generada por el LLM")
    sources: list[SourceDocument] = Field(..., description="Fuentes utilizadas para responder")
    crag_status: str = Field(..., description="Estado del flujo CRAG (CORRECT | AMBIGUOUS | NO_DATA_FOUND)")
    latency_ms: LatencyBreakdown = Field(..., description="Desglose de latencia")


# ── Endpoints ──────────────────────────────────────────────


@router.post(
    "/query",
    response_model=ChatQueryResponse,
    status_code=status.HTTP_200_OK,
    summary="Realizar una consulta inteligente (CRAG)",
    description=(
        "Envía una pregunta sobre el contenido indexado. "
        "El motor realiza búsqueda híbrida y reordenamiento, "
        "evalúa la relevancia del contenido, reescribe la consulta "
        "si es necesario y genera una respuesta con citas de forma segura."
    ),
)
async def query_chat(
    payload: ChatQueryRequest,
    engine: CRAGEngine = Depends(get_crag_engine),
) -> dict:
    """Ejecuta una consulta inteligente RAG y retorna la respuesta con citas y latencias."""
    logger.info("Recibida consulta de chat: '%s'", payload.query)
    
    try:
        result = await engine.execute_query(
            query=payload.query, 
            document_ids=payload.document_ids
        )
        return result
    except Exception as exc:
        logger.exception("Fallo catastrófico al procesar la query de chat: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Fallo interno en el motor de consulta CRAG: {exc}",
        )
