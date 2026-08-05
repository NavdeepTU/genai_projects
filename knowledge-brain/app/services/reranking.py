import logging

import voyageai

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings
from app.models.document import Chunk

logger = logging.getLogger(__name__)

settings = get_settings()
client = voyageai.AsyncClient(api_key=settings.voyage_api_key)
circuit_breaker = CircuitBreaker(name="voyage_reranking")


async def rerank_chunks(question: str, chunks: list[Chunk], top_k: int) -> list[Chunk]:
    """Reorder candidate chunks by how well each actually answers the question.

    Unlike vector/keyword search, which score the question and a chunk
    separately, Voyage's reranker looks at both together in one pass —
    slower per chunk, but far more accurate, which is why it only runs
    against this already-narrowed-down candidate list, not every chunk
    in the database.
    """
    if not chunks:
        return []

    response = await circuit_breaker.call(
        lambda: client.rerank(
            query=question,
            documents=[chunk.text for chunk in chunks],
            model=settings.reranking_model,
            top_k=top_k,
        )
    )

    return [chunks[result.index] for result in response.results]
