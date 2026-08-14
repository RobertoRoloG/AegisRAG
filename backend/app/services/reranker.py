"""
AegisRAG — Servicio de Re-Ranking.

Usa un modelo local Cross-Encoder (vía FastEmbed) para evaluar la
relevancia de los fragmentos recuperados en relación a la consulta.
Ordena y filtra los mejores candidatos aplicando un umbral estricto.
"""

import logging

from fastembed.rerank.cross_encoder import TextCrossEncoder

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Instancia global de Cross-Encoder (singleton lazy) ─────
_reranker_model: TextCrossEncoder | None = None


def _get_reranker_model() -> TextCrossEncoder:
    """
    Retorna el singleton del modelo Cross-Encoder.
    La primera llamada descarga el modelo si no está en la caché local.
    """
    global _reranker_model
    if _reranker_model is None:
        logger.info("Cargando modelo Cross-Encoder Reranker: %s", settings.reranker_model)
        _reranker_model = TextCrossEncoder(model_name=settings.reranker_model)
        logger.info("Reranker cargado correctamente")
    return _reranker_model


class ReRankerService:
    """Clase de negocio para evaluar la relevancia de los fragmentos."""

    def __init__(self) -> None:
        # Forzar inicialización del modelo al instanciar el servicio
        self.model = _get_reranker_model()

    def rerank(self, query: str, documents: list[dict], top_n: int = 3) -> list[dict]:
        """
        Reordena fragmentos basándose en su puntuación de relevancia Cross-Encoder.

        Args:
            query: Consulta original del usuario.
            documents: Lista de diccionarios de fragmentos devueltos por la búsqueda.
            top_n: Número máximo de elementos ordenados a retornar.

        Returns:
            Lista de fragmentos reordenados y anotados con su score de rerank.
        """
        if not documents:
            logger.info("No hay documentos para reordenar.")
            return []

        logger.info(
            "Re-Ranking de %d documentos para la query: '%s' (top_n=%d)",
            len(documents),
            query,
            top_n,
        )

        # Extraer textos para el Cross-Encoder
        texts = [doc["text"] for doc in documents]

        # El método rerank de FastEmbed genera un iterable de floats (logits)
        logits = list(self.model.rerank(query, texts))

        import math

        # Reconstruir lista aplicando sigmoide para normalizar a probabilidades [0, 1]
        reranked_docs = []
        for idx, logit in enumerate(logits):
            # Sigmoide: 1 / (1 + exp(-x))
            try:
                score = 1.0 / (1.0 + math.exp(-float(logit)))
            except OverflowError:
                # Evitar overflow en exponenciales muy grandes/pequeñas
                score = 1.0 if float(logit) > 0 else 0.0
            
            # Copiar metadatos del documento original y añadir score
            doc_info = dict(documents[idx])
            doc_info["rerank_score"] = score
            reranked_docs.append(doc_info)

        # Ordenar de mayor a menor score
        reranked_docs.sort(key=lambda x: x["rerank_score"], reverse=True)

        # Limitar al top_n solicitado
        final_results = reranked_docs[:top_n]

        logger.info(
            "Re-Ranking completado. Mejor score: %0.4f, Peor score en top: %0.4f",
            final_results[0]["rerank_score"] if final_results else 0.0,
            final_results[-1]["rerank_score"] if final_results else 0.0,
        )
        return final_results


# Instancia singleton para inyección o uso directo
reranker_service = ReRankerService()


def get_reranker_service() -> ReRankerService:
    """Retorna la instancia singleton del servicio Reranker."""
    return reranker_service
