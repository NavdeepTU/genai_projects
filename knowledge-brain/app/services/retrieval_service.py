import asyncio
import logging
import time
import uuid

from openai import OpenAIError
from sqlalchemy.exc import SQLAlchemyError

from app.core.circuit_breaker import CircuitOpenError
from app.core.config import get_settings
from app.core.middleware import get_correlation_id
from app.models.document import Chunk
from app.models.query import QuerySource
from app.repositories.document_repository import DocumentRepository
from app.repositories.graph_repository import GraphRepository
from app.services.embedding import embed_chunks
from app.services.generation import generate_answer
from app.services.hybrid_search import reciprocal_rank_fusion
from app.services.injection_detection import check_injection
from app.services.jailbreak_detection import check_jailbreak
from app.services.moderation import check_moderation
from app.services.query_graph import MAX_RETRIES, QueryState, build_query_graph
from app.services.query_rewriting import rewrite_query
from app.services.reranking import rerank_chunks

settings = get_settings()
logger = logging.getLogger(__name__)

# Deliberately the same message whether a question got blocked before
# retrieval even ran, or an answer got blocked after generation — never
# telling the caller *which* check tripped, or *when* in the pipeline,
# since that's exactly the kind of feedback that helps someone refine
# an attack.
BLOCKED_MESSAGE = "I can't help with that — it didn't pass a safety check. Try rephrasing your question."


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

    def __init__(self, repository: DocumentRepository, graph_repository: GraphRepository) -> None:
        self.repository = repository
        self.graph_repository = graph_repository
        self._graph = build_query_graph(self)

    async def _prepare_for_generation(
        self, question: str, user_id: str, domain: str | None = None
    ) -> QueryState:
        """Run the graph up through graph context — everything generation needs,
        stopping one step short of actually generating an answer (see ADR-043).

        This is the seam streamed answer generation needs: the graph itself
        has no idea whether its caller wants a blocking answer or a streamed
        one, it just gathers what generation will need. If the input
        guardrail blocked the question, the graph's own conditional routing
        sends it straight to its end, so the state comes back already
        blocked, with generation never having been reached — exactly as
        before this method existed, just without generation being part of
        the same graph invocation.
        """
        initial_state: QueryState = {
            "original_question": question,
            "question": question,
            "user_id": user_id,
            "domain": domain,
            "candidates": [],
            "reranked_chunks": [],
            "top_relevance_score": 0.0,
            "reranker_unavailable": False,
            "retry_count": 0,
            "graph_context": [],
            "answer": "",
            "duration_ms": 0.0,
            "blocked": False,
            "block_reason": None,
        }
        # metadata here tags the *entire* trace for this query — every
        # node inside it, and every OpenAI/Voyage call any node makes —
        # with who asked and which request this was, so a LangSmith trace
        # can be filtered by user or cross-referenced back to our own
        # logs and audit entries via correlation_id.
        return await self._graph.ainvoke(
            initial_state,
            config={
                "metadata": {"user_id": user_id, "correlation_id": get_correlation_id()},
                "run_name": "query",
            },
        )

    async def run_query(self, question: str, user_id: str, domain: str | None = None) -> QueryState:
        """Run one question through the full pipeline and return the final state.

        domain optionally restricts retrieval to documents tagged with that
        one domain — used by FederatedRetrievalService to run one domain-
        scoped pass per relevant domain. Left as None, this is the exact
        same unrestricted single-domain pipeline that existed before that
        feature — the common case pays nothing extra. Generation and the
        output guardrail run as plain method calls after the graph
        returns, not as graph nodes themselves (see ADR-043) — behaviorally
        identical to when they were, since a blocked question already
        skipped them via the graph's own routing either way.
        """
        start = time.monotonic()
        state = await self._prepare_for_generation(question, user_id, domain)
        if not state["blocked"]:
            state.update(await self._generate_node(state))
            state.update(await self._output_guardrail_node(state))
        state["duration_ms"] = (time.monotonic() - start) * 1000
        return state

    async def build_sources_and_confidence(
        self, state: QueryState
    ) -> tuple[list[QuerySource], float | None]:
        """Turn a finished QueryState into what the REST response actually shows.

        Lives here, not in the route, so it's testable without a running
        HTTP server — the route should stay a thin translation from
        QueryState to QueryResponse, not the place this logic runs.
        """
        if state["blocked"]:
            # A blocked answer shows no sources and no confidence — showing
            # the exact retrieved chunk that tripped the guardrail would
            # defeat the point of blocking in the first place.
            return [], None

        filenames: dict[uuid.UUID, str] = {}
        sources: list[QuerySource] = []
        for chunk in state["reranked_chunks"]:
            if chunk.document_id not in filenames:
                document = await self.repository.get_by_id(chunk.document_id)
                filenames[chunk.document_id] = document.filename if document else "Unknown document"
            sources.append(
                QuerySource(
                    document_id=chunk.document_id,
                    filename=filenames[chunk.document_id],
                    chunk_text=chunk.text,
                )
            )

        confidence = None if state["reranker_unavailable"] else state["top_relevance_score"]
        return sources, confidence

    async def _input_guardrail_node(self, state: QueryState) -> dict:
        """Graph node, and the graph's entry point: block a bad question before it costs anything.

        Same two-check, availability-aware shape as the output guardrail
        (see _output_guardrail_node) — a moderation classifier (reused as-is;
        it works on any text, not just answers) and check_jailbreak, a
        judge for direct injection/jailbreak attempts typed straight
        into the question, as opposed to check_injection's job of
        catching *indirect* injection smuggled in through a document.
        Running this first, before retrieval or generation happen at
        all, means a bad question never pays for either.
        """
        (moderation_flagged, moderation_available), (jailbreak_flagged, jailbreak_available) = (
            await asyncio.gather(
                self._check_moderation_safely(state["question"]),
                self._check_jailbreak_safely(state["question"]),
            )
        )

        if not moderation_available and not jailbreak_available:
            return {
                "answer": BLOCKED_MESSAGE,
                "blocked": True,
                "block_reason": "input_guardrails_unavailable",
            }

        if moderation_flagged or jailbreak_flagged:
            reason = "input_moderation" if moderation_flagged else "jailbreak"
            return {"answer": BLOCKED_MESSAGE, "blocked": True, "block_reason": reason}

        return {"blocked": False, "block_reason": None}

    def _should_proceed_after_input_check(self, state: QueryState) -> str:
        """Route to retrieval if the question passed, straight to the end if it didn't."""
        return "block" if state["blocked"] else "proceed"

    async def _check_jailbreak_safely(self, question: str) -> tuple[bool, bool]:
        """Run the jailbreak check; on failure, report unavailable rather than raising."""
        try:
            return await check_jailbreak(question), True
        except (CircuitOpenError, OpenAIError):
            logger.error(
                "Jailbreak check unavailable", extra={"correlation_id": get_correlation_id()}
            )
            return False, False

    async def _retrieve_node(self, state: QueryState) -> dict:
        """Graph node: hybrid search for the current question, merged with RRF."""
        [query_embedding] = await embed_chunks([state["question"]])

        # Run sequentially, not concurrently: both share one AsyncSession,
        # which isn't safe for two queries running at the same time.
        vector_chunks, vector_failed = await self._find_similar_chunks_safely(
            query_embedding, state["user_id"], state["domain"]
        )
        keyword_chunks, keyword_failed = await self._find_by_keyword_safely(
            state["question"], state["user_id"], state["domain"]
        )

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
        return "proceed"

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

    async def _graph_context_node(self, state: QueryState) -> dict:
        """Graph node: pull in snippets from documents the reranked chunks' sources reference."""
        document_ids = {str(chunk.document_id) for chunk in state["reranked_chunks"]}

        snippets: list[str] = []
        for document_id in document_ids:
            referenced_ids, unavailable = await self._fetch_graph_context_safely(document_id)
            if unavailable:
                continue
            for referenced_id in referenced_ids:
                try:
                    snippet = await self.repository.get_first_chunk_text(
                        uuid.UUID(referenced_id), state["user_id"]
                    )
                except SQLAlchemyError:
                    logger.error(
                        "Failed to fetch snippet for referenced document %s",
                        referenced_id,
                        extra={"correlation_id": get_correlation_id()},
                    )
                    await self.repository.rollback()
                    continue
                if snippet:
                    snippets.append(snippet)

        return {"graph_context": snippets}

    async def _fetch_graph_context_safely(self, document_id: str) -> tuple[list[str], bool]:
        """Look up directly-referenced documents; on failure, report unavailable rather than raising."""
        try:
            return await self.graph_repository.get_referenced_documents(document_id), False
        except CircuitOpenError:
            logger.error(
                "Graph lookup unavailable, answering without related-document context",
                extra={"correlation_id": get_correlation_id()},
            )
            return [], True

    async def _generate_node(self, state: QueryState) -> dict:
        """Generate the final answer from the original question.

        No longer a graph node itself (see ADR-043) — called directly by
        run_query, and bypassed entirely by the streaming endpoint, which
        calls a streaming generation function instead once the graph
        returns.
        """
        context_chunks = [chunk.text for chunk in state["reranked_chunks"]] + state["graph_context"]
        answer = await generate_answer(state["original_question"], context_chunks)
        return {"answer": answer}

    async def _output_guardrail_node(self, state: QueryState) -> dict:
        """Block the answer if a safety check flags it.

        No longer a graph node itself (see ADR-043), called directly by
        run_query right after generation. The streaming endpoint runs its
        own equivalent instead — per-sentence moderation as chunks are
        produced, plus this exact injection check once the full answer is
        known — since neither check can run against text that doesn't
        exist yet.

        Two independent checks run concurrently — a moderation classifier
        (unsafe content) and an LLM judge (prompt injection smuggled in
        through retrieved document text). If a check's own circuit is
        open, that check contributes no signal rather than forcing a
        block on its own — but if *neither* check could run at all,
        there's no signal whatsoever, and that's treated as unsafe: a
        clean answer proven safe by nothing is not the same as a clean
        answer actually checked.
        """
        context_chunks = [chunk.text for chunk in state["reranked_chunks"]] + state["graph_context"]

        (moderation_flagged, moderation_available), (injection_flagged, injection_available) = (
            await asyncio.gather(
                self._check_moderation_safely(state["answer"]),
                self._check_injection_safely(state["original_question"], state["answer"], context_chunks),
            )
        )

        if not moderation_available and not injection_available:
            return {
                "answer": BLOCKED_MESSAGE,
                "blocked": True,
                "block_reason": "guardrails_unavailable",
            }

        if moderation_flagged or injection_flagged:
            reason = "moderation" if moderation_flagged else "injection"
            return {"answer": BLOCKED_MESSAGE, "blocked": True, "block_reason": reason}

        return {"blocked": False, "block_reason": None}

    async def _check_moderation_safely(self, answer: str) -> tuple[bool, bool]:
        """Run the moderation check; on failure, report unavailable rather than raising.

        Returns (flagged, available) — unavailable contributes no signal
        of its own, it's not treated as "checked and clean." See
        _output_guardrail_node for what happens when both checks end up
        unavailable at once.
        """
        try:
            return await check_moderation(answer), True
        except (CircuitOpenError, OpenAIError):
            logger.error(
                "Moderation check unavailable", extra={"correlation_id": get_correlation_id()}
            )
            return False, False

    async def _check_injection_safely(
        self, question: str, answer: str, context_chunks: list[str]
    ) -> tuple[bool, bool]:
        """Run the injection check; on failure, report unavailable rather than raising."""
        try:
            return await check_injection(question, answer, context_chunks), True
        except (CircuitOpenError, OpenAIError):
            logger.error(
                "Injection check unavailable", extra={"correlation_id": get_correlation_id()}
            )
            return False, False

    async def _find_similar_chunks_safely(
        self, query_embedding: list[float], user_id: str, domain: str | None = None
    ) -> tuple[list[Chunk], bool]:
        """Run vector search; on failure, roll back and report no results rather than raising."""
        try:
            chunks = await self.repository.find_similar_chunks(
                query_embedding, user_id, limit=settings.retrieval_candidate_pool, domain=domain
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

    async def _find_by_keyword_safely(
        self, question: str, user_id: str, domain: str | None = None
    ) -> tuple[list[Chunk], bool]:
        """Run keyword search; on failure, roll back and report no results rather than raising."""
        try:
            chunks = await self.repository.find_by_keyword(
                question, user_id, limit=settings.retrieval_candidate_pool, domain=domain
            )
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
