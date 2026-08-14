"""
AegisRAG — Motor Grafo Corrective RAG (CRAG).

Implementa la máquina de estados de CRAG de forma asíncrona:
- RETRIEVE: Recuperación híbrida + Re-Ranking.
- GRADE: Evaluación de relevancia contra un umbral (threshold=0.35).
- DECISION & REWRITE: Si es irrelevante, reescribe la query con LLM y reintenta.
- GENERATE: Genera respuesta final restrictiva con citas o retorna un mensaje seguro.
"""

import asyncio
import logging
import time
from typing import Any, Literal

from app.core.config import get_settings
from app.services.llm import get_llm_service
from app.services.reranker import get_reranker_service
from app.services.retrieval import hybrid_search

logger = logging.getLogger(__name__)
settings = get_settings()


class CRAGEngine:
    """Motor de orquestación del grafo de decisión Corrective RAG (CRAG)."""

    def __init__(self) -> None:
        self.llm = get_llm_service()
        self.reranker = get_reranker_service()
        self.threshold = settings.crag_relevance_threshold

    async def execute_query(
        self, 
        query: str, 
        document_ids: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Ejecuta el flujo completo de Corrective RAG (CRAG) midiendo latencias individuales.

        Args:
            query: Consulta original del usuario.
            document_ids: Lista opcional de IDs de documentos para filtrar el contexto.

        Returns:
            Diccionario estructurado con la respuesta del LLM, fuentes, estado y latencias.
        """
        start_total = time.perf_counter()
        latencies = {
            "retrieval": 0.0,
            "rewrite": 0.0,
            "generation": 0.0,
            "total": 0.0,
        }

        # ── 1. Nodo: RETRIEVE ──────────────────────────────
        start_ret = time.perf_counter()
        # Búsqueda híbrida asíncrona
        candidates = await hybrid_search(query, document_ids=document_ids, top_k=20)
        
        # Re-Ranking ejecutado en hilo secundario (evita bloqueo de CPU de FastAPI)
        top_chunks = await asyncio.to_thread(self.reranker.rerank, query, candidates, top_n=7)
        latencies["retrieval"] = round((time.perf_counter() - start_ret) * 1000, 2)

        # ── 2. Nodo: GRADE ─────────────────────────────────
        # Evaluamos si hay coincidencias literales de nombres propios o palabras de la query
        query_terms = [w.lower().strip() for w in query.split() if len(w) >= 3]
        has_literal_match = False

        if top_chunks and query_terms:
            for chunk in top_chunks:
                chunk_lower = chunk["text"].lower()
                if any(term in chunk_lower for term in query_terms):
                    has_literal_match = True
                    break

        max_score = top_chunks[0]["rerank_score"] if top_chunks else 0.0
        # Si existe coincidencia literal o la consulta es una palabra corta/nombre propio, adaptar el umbral
        effective_threshold = 0.01 if has_literal_match else self.threshold

        logger.info(
            "Evaluación CRAG. Máximo score: %0.4f (Umbral efectivo: %0.2f, Coincidencia exacta: %s)",
            max_score,
            effective_threshold,
            has_literal_match,
        )

        crag_status: Literal["CORRECT", "AMBIGUOUS", "NO_DATA_FOUND"] = "CORRECT"
        final_chunks = top_chunks
        query_used = query

        # Si el score está por debajo del umbral efectivo y tampoco hay coincidencia exacta
        if max_score < effective_threshold and not has_literal_match:
            logger.warning(
                "Fragmentos por debajo del umbral (%0.4f < %0.2f). Iniciando reescritura de query.",
                max_score,
                effective_threshold,
            )
            
            # ── 3. Nodo: QUERY REWRITE & RETRY ─────────────
            start_rew = time.perf_counter()
            crag_status = "AMBIGUOUS"
            
            # Reescribir la query usando el LLM
            query_used = await self.llm.rewrite_query(query)
            
            # Reintentar búsqueda híbrida asíncrona con la query optimizada
            retry_candidates = await hybrid_search(query_used, document_ids=document_ids, top_k=20)
            retry_chunks = await asyncio.to_thread(self.reranker.rerank, query_used, retry_candidates, top_n=7)
            
            latencies["rewrite"] = round((time.perf_counter() - start_rew) * 1000, 2)

            # Re-evaluar score de la nueva búsqueda
            retry_max_score = retry_chunks[0]["rerank_score"] if retry_chunks else 0.0
            logger.info("Evaluación tras reintento. Score: %0.4f", retry_max_score)

            if retry_max_score < effective_threshold:
                # Si el segundo intento vuelve a fallar, caemos a NO_DATA_FOUND para evitar alucinaciones
                logger.error("El reintento también falló por debajo del umbral. Estado: NO_DATA_FOUND.")
                crag_status = "NO_DATA_FOUND"
                final_chunks = []
            else:
                # Si el reintento funcionó, lo marcamos como corregido
                logger.info("Reintento de búsqueda híbrida exitoso.")
                final_chunks = retry_chunks

        # ── 4. Nodo: GENERATE ──────────────────────────────
        start_gen = time.perf_counter()
        
        if crag_status == "NO_DATA_FOUND":
            answer = (
                "Lo siento, no he encontrado información relevante en los documentos indexados "
                "para responder a tu pregunta de manera precisa. Para evitar alucinaciones, "
                "prefiero no formular una respuesta basada en especulaciones."
            )
        else:
            # Construir contexto para el LLM con etiquetas explícitas de cita
            context_blocks = []
            for i, chunk in enumerate(final_chunks, start=1):
                context_blocks.append(
                    f"Cita requerida para este texto: [{chunk['filename']}, pág. {chunk['page_number']}]\n"
                    f"Texto: {chunk['text']}\n"
                )
            context_str = "\n---\n".join(context_blocks)

            system_prompt = (
                "Eres AegisRAG, un asistente de investigación preciso.\n\n"
                "REGLAS EStrictAS DE FORMATO Y CITACIÓN:\n"
                "1. CITAS INLINE EN CADA PÁRRAFO: Cada párrafo o dato de tu respuesta DEBE incluir obligatoriamente su cita [nombre_archivo.pdf, pág. X] intercalada al final de la oración/párrafo.\n"
                "2. SIN SECCIÓN SEPARADA DE REFERENCIAS: Queda prohibido crear listas finales de 'Referencias', 'Fuentes' o 'Bibliografía' al final del mensaje.\n"
                "3. SIN ETIQUETAS GENÉRICAS: No escribas expresiones como 'En el Fragmento [1]' ni 'Según la Fuente 1'. En su lugar, redacta la información directamente e inserta la cita clicable [nombre_archivo.pdf, pág. X] al final de la frase.\n"
                "4. RIGUROSIDAD ABSOLUTA: Toda afirmación debe basarse exclusivamente en el texto provisto."
            )

            prompt = (
                f"Consulta del usuario: {query}\n\n"
                f"Contexto disponible:\n{context_str}\n\n"
                f"Respuesta redactada con citas intercaladas en cada párrafo con el formato [nombre_archivo.pdf, pág. X]:"
            )

            try:
                answer = await self.llm.generate_response(prompt, system_prompt)
            except Exception as exc:
                logger.exception("Fallo durante la llamada al LLM para generación.")
                answer = f"Error interno en la generación de la respuesta: {exc}"

        latencies["generation"] = round((time.perf_counter() - start_gen) * 1000, 2)
        latencies["total"] = round((time.perf_counter() - start_total) * 1000, 2)

        # Dar formato final a las fuentes para la API
        sources = []
        for chunk in final_chunks:
            sources.append({
                "doc_id": chunk["doc_id"],
                "filename": chunk["filename"],
                "page_number": chunk["page_number"],
                "score": round(chunk["rerank_score"], 4),
                "snippet": chunk["text"],
            })

        return {
            "answer": answer,
            "sources": sources,
            "crag_status": crag_status,
            "query_used": query_used,
            "latency_ms": latencies,
        }


# Instancia singleton
crag_engine = CRAGEngine()


def get_crag_engine() -> CRAGEngine:
    """Retorna la instancia singleton de CRAGEngine."""
    return crag_engine
