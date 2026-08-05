import logging

from sqlalchemy.exc import SQLAlchemyError

from app.core.circuit_breaker import CircuitOpenError
from app.core.config import get_settings
from app.core.middleware import get_correlation_id
from app.models.document import Chunk
from app.repositories.document_repository import DocumentRepository
from app.services.embedding import embed_chunks
from app.services.generation import generate_answer
from app.services.hybrid_search import reciprocal_rank_fusion
from app.services.reranking import rerank_chunks

settings = get_settings()
logger = logging.getLogger(__name__)


class RetrievalUnavailableError(Exception):
    """Raised when both vector and keyword search fail for one request."""


class RetrievalService:
    """Answers a question using retrieval-augmented generation (RAG).

    Embeds the question, finds the most relevant stored chunks via
    hybrid search (vector + keyword), then asks an LLM to answer using
    only those chunks — mirroring IngestionService's role as the one
    place that knows step order.
    """

    def __init__(self, repository: DocumentRepository) -> None:
        self.repository = repository

    async def answer_question(self, question: str) -> str:
        """Run one question through hybrid retrieval, reranking, then generation."""
        [query_embedding] = await embed_chunks([question])

        # Run sequentially, not concurrently: both share one AsyncSession,
        # which isn't safe for two queries running at the same time.
        vector_chunks, vector_failed = await self._find_similar_chunks_safely(query_embedding)
        keyword_chunks, keyword_failed = await self._find_by_keyword_safely(question)

        if vector_failed and keyword_failed:
            raise RetrievalUnavailableError("Both vector and keyword search failed")

        candidates = reciprocal_rank_fusion(vector_chunks, keyword_chunks, limit=settings.retrieval_candidate_pool)
        chunks = await self._rerank_safely(question, candidates)
        context_chunks = [chunk.text for chunk in chunks]
        return await generate_answer(question, context_chunks)

    async def _find_similar_chunks_safely(self, query_embedding: list[float]) -> tuple[list[Chunk], bool]:
        """Run vector search; on failure, roll back and report no results rather than raising."""
        try:
            chunks = await self.repository.find_similar_chunks(
                query_embedding, limit=settings.retrieval_candidate_pool
            )
            self.repository.detach(chunks)
            return chunks, False
        except SQLAlchemyError:
            logger.error(
                "Vector search failed, falling back to keyword search alone",
                extra={"correlation_id": get_correlation_id()},
            )
            await self.repository.rollback()
            return [], True

    async def _find_by_keyword_safely(self, question: str) -> tuple[list[Chunk], bool]:
        """Run keyword search; on failure, roll back and report no results rather than raising."""
        try:
            chunks = await self.repository.find_by_keyword(question, limit=settings.retrieval_candidate_pool)
            self.repository.detach(chunks)
            return chunks, False
        except SQLAlchemyError:
            logger.error(
                "Keyword search failed, falling back to vector search alone",
                extra={"correlation_id": get_correlation_id()},
            )
            await self.repository.rollback()
            return [], True

    async def _rerank_safely(self, question: str, candidates: list[Chunk]) -> list[Chunk]:
        """Rerank candidates; on failure, fall back to hybrid search's own RRF order."""
        try:
            return await rerank_chunks(question, candidates, top_k=settings.retrieval_top_k)
        except CircuitOpenError:
            logger.error(
                "Reranking unavailable, falling back to hybrid search's own ranking",
                extra={"correlation_id": get_correlation_id()},
            )
            return candidates[: settings.retrieval_top_k]
