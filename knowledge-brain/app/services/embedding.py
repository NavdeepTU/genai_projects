import logging

from openai import AsyncOpenAI, OpenAIError

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
client = AsyncOpenAI(api_key=settings.openai_api_key)
circuit_breaker = CircuitBreaker(name="openai_embeddings")


async def embed_chunks(chunks: list[str]) -> list[list[float]]:
    """Convert text chunks into embedding vectors, one vector per chunk.

    All chunks go out in a single API call instead of one call per
    chunk, since OpenAI's embeddings endpoint accepts a batch — fewer
    network round trips, and much faster for documents with many
    chunks.
    """
    if not chunks:
        return []

    try:
        response = await circuit_breaker.call(
            lambda: client.embeddings.create(model=settings.embedding_model, input=chunks)
        )
    except OpenAIError:
        logger.exception("Failed to embed %d chunks", len(chunks))
        raise

    return [item.embedding for item in response.data]
