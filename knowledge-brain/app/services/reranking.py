import logging
from dataclasses import dataclass

import voyageai

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings
from app.models.document import Chunk

logger = logging.getLogger(__name__)

settings = get_settings()
client = voyageai.AsyncClient(api_key=settings.voyage_api_key)
circuit_breaker = CircuitBreaker(name="voyage_reranking")


@dataclass
class RankedChunk:
    """A chunk paired with how relevant Voyage judged it to be, 0 to 1."""

    chunk: Chunk
    relevance_score: float


async def rerank_chunks(question: str, chunks: list[Chunk], top_k: int) -> list[RankedChunk]:
    """Reorder candidate chunks by how well each actually answers the question.

    Unlike vector/keyword search, which score the question and a chunk
    separately, Voyage's reranker looks at both together in one pass —
    slower per chunk, but far more accurate, which is why it only runs
    against this already-narrowed-down candidate list, not every chunk
    in the database. Returns each chunk's relevance score alongside it,
    not just the chunk, so callers can judge how confident this ranking
    actually is instead of only seeing the reordered list.
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

    return [
        RankedChunk(chunk=chunks[result.index], relevance_score=result.relevance_score)
        for result in response.results
    ]
