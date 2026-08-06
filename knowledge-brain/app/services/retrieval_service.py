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
from app.services.query_graph import MAX_RETRIES, QueryState, build_query_graph
from app.services.query_rewriting import rewrite_query
from app.services.reranking import rerank_chunks

settings = get_settings()
logger = logging.getLogger(__name__)


class RetrievalUnavailableError(Exception):
    """Raised when both vector and keyword search fail for one request."""


class RetrievalService:
    """Answers a question using retrieval-augmented generation (RAG).

    Runs the question through a LangGraph pipeline: hybrid search
    (vector + keyword) → rerank → generate, with one conditional loop
    back to a rewritten search if reranking comes back empty — mirroring
    IngestionService's role as the one place that knows step order, but
    as a graph instead of a fixed sequence, since the order can now
    change based on what's actually found.
    """

    def __init__(self, repository: DocumentRepository) -> None:
        self.repository = repository
        self._graph = build_query_graph(self)

    async def answer_question(self, question: str) -> str:
        """Run one question through the query graph and return the final answer."""
        initial_state: QueryState = {
            "original_question": question,
            "question": question,
            "candidates": [],
            "reranked_chunks": [],
            "top_relevance_score": 0.0,
            "reranker_unavailable": False,
            "retry_count": 0,
            "answer": "",
        }
        result = await self._graph.ainvoke(initial_state)
        return result["answer"]

    async def _retrieve_node(self, state: QueryState) -> dict:
        """Graph node: hybrid search for the current question, merged with RRF."""
        [query_embedding] = await embed_chunks([state["question"]])

        # Run sequentially, not concurrently: both share one AsyncSession,
        # which isn't safe for two queries running at the same time.
        vector_chunks, vector_failed = await self._find_similar_chunks_safely(query_embedding)
        keyword_chunks, keyword_failed = await self._find_by_keyword_safely(state["question"])

        if vector_failed and keyword_failed:
            raise RetrievalUnavailableError("Both vector and keyword search failed")

        candidates = reciprocal_rank_fusion(
            vector_chunks, keyword_chunks, limit=settings.retrieval_candidate_pool
        )
        return {"candidates": candidates}

    async def _rerank_node(self, state: QueryState) -> dict:
        """Graph node: rerank this round's candidates."""
        chunks, top_score, reranker_unavailable = await self._rerank_safely(
            state["question"], state["candidates"]
        )
        return {
            "reranked_chunks": chunks,
            "top_relevance_score": top_score,
            "reranker_unavailable": reranker_unavailable,
        }

    def _should_retry(self, state: QueryState) -> str:
        """Decide whether to rewrite the question and search again, or move on.

        Skips the retry entirely if reranking itself was unavailable —
        there's no real score to judge in that case, and we've already
        degraded once by falling back to hybrid search's own order;
        piling a second retry on top of that isn't worth the extra cost.
        """
        weak_results = state["top_relevance_score"] < settings.retrieval_relevance_threshold
        can_retry = state["retry_count"] < MAX_RETRIES
        if weak_results and can_retry and not state["reranker_unavailable"]:
            return "rewrite"
        return "generate"

    async def _rewrite_node(self, state: QueryState) -> dict:
        """Graph node: rephrase the question and count this attempt."""
        try:
            new_question = await rewrite_query(state["question"])
        except CircuitOpenError:
            logger.error(
                "Query rewriting unavailable, retrying the same question once",
                extra={"correlation_id": get_correlation_id()},
            )
            new_question = state["question"]
        return {"question": new_question, "retry_count": state["retry_count"] + 1}

    async def _generate_node(self, state: QueryState) -> dict:
        """Graph node: generate the final answer from the original question."""
        context_chunks = [chunk.text for chunk in state["reranked_chunks"]]
        answer = await generate_answer(state["original_question"], context_chunks)
        return {"answer": answer}

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

    async def _rerank_safely(
        self, question: str, candidates: list[Chunk]
    ) -> tuple[list[Chunk], float, bool]:
        """Rerank candidates; on failure, fall back to hybrid search's own RRF order.

        Returns the chunks, the top chunk's relevance score, and whether
        reranking itself failed. The failure flag exists because a
        fallback order has no real score behind it — 0.0 there would
        look identical to "genuinely searched and found nothing," which
        isn't true.
        """
        try:
            ranked = await rerank_chunks(question, candidates, top_k=settings.retrieval_top_k)
            top_score = ranked[0].relevance_score if ranked else 0.0
            return [r.chunk for r in ranked], top_score, False
        except CircuitOpenError:
            logger.error(
                "Reranking unavailable, falling back to hybrid search's own ranking",
                extra={"correlation_id": get_correlation_id()},
            )
            return candidates[: settings.retrieval_top_k], 0.0, True
