import asyncio
import logging
import time
from dataclasses import dataclass

from openai import OpenAIError

from app.core.circuit_breaker import CircuitOpenError
from app.core.middleware import get_correlation_id
from app.models.query import QuerySource
from app.repositories.document_repository import DocumentRepository
from app.repositories.graph_repository import GraphRepository
from app.services.domain_classification import classify_domains
from app.services.query_graph import QueryState
from app.services.retrieval_service import (
    BLOCKED_MESSAGE,
    RetrievalService,
    RetrievalUnavailableError,
)
from app.services.synthesis import synthesize_answers

logger = logging.getLogger(__name__)


@dataclass
class FederatedResult:
    """What a caller actually needs back, whether one domain answered or several did."""

    answer: str
    sources: list[QuerySource]
    confidence: float | None
    duration_ms: float
    blocked: bool
    block_reason: str | None
    domains_used: list[str]
    partial: bool = False


@dataclass
class _DomainRun:
    domain: str
    state: QueryState
    sources: list[QuerySource]


class FederatedRetrievalService:
    """The one entry point every caller uses to answer a question.

    A supervisor call (classify_domains) decides which domain(s), if any,
    the question needs, using only domains this user actually has
    accessible documents in. Zero or one domain needed delegates straight
    to RetrievalService.run_query, completely unchanged — the common case
    pays no extra latency or cost, same as ADR-040 describes. Two or more
    domains needed runs one full RetrievalService pass per domain,
    concurrently, each producing its own complete draft answer — not just
    a shared pool of chunks — then a synthesis call merges those drafts
    into one answer, which gets one more moderation+injection safety pass
    before it's returned, on top of the pass each domain's own answer
    already went through individually.
    """

    def __init__(self, repository: DocumentRepository, graph_repository: GraphRepository) -> None:
        self.repository = repository
        self.graph_repository = graph_repository
        self._single = RetrievalService(repository, graph_repository)

    async def run_query(self, question: str, user_id: str) -> FederatedResult:
        """Answer a question, routing across domains only when the question actually needs it."""
        start = time.monotonic()

        available_domains = await self.repository.list_domains_for_user(user_id)
        domains = await self._classify_domains_safely(question, available_domains)

        if len(domains) <= 1:
            return await self._run_single_domain(question, user_id, domains, start)
        return await self._run_federated(question, user_id, domains, start)

    async def _classify_domains_safely(self, question: str, available_domains: list[str]) -> list[str]:
        """Classify domains; on failure or an empty domain set, fall back to unrestricted search.

        A user with no domain-tagged documents at all is the overwhelmingly
        common case for now (domains are opt-in, set manually at upload —
        see ADR-040), so this is the normal path today, not an edge case.
        """
        if not available_domains:
            return []
        try:
            return await classify_domains(question, available_domains)
        except (CircuitOpenError, OpenAIError):
            logger.error(
                "Domain classification unavailable, answering unrestricted",
                extra={"correlation_id": get_correlation_id()},
            )
            return []

    async def _run_single_domain(
        self, question: str, user_id: str, domains: list[str], start: float
    ) -> FederatedResult:
        domain = domains[0] if domains else None
        state = await self._single.run_query(question, user_id, domain)
        sources, confidence = await self._single.build_sources_and_confidence(state)
        return FederatedResult(
            answer=state["answer"],
            sources=sources,
            confidence=confidence,
            duration_ms=(time.monotonic() - start) * 1000,
            blocked=state["blocked"],
            block_reason=state["block_reason"],
            domains_used=domains,
        )

    async def _run_federated(
        self, question: str, user_id: str, domains: list[str], start: float
    ) -> FederatedResult:
        runs = await asyncio.gather(
            *(self._run_one_domain_safely(question, user_id, domain) for domain in domains)
        )
        succeeded = [run for run in runs if run is not None]
        if not succeeded:
            raise RetrievalUnavailableError("Every domain's retrieval pass failed")

        answerable = [run for run in succeeded if not run.state["blocked"]]
        partial = len(succeeded) < len(domains)

        if not answerable:
            # Every domain that came back got blocked by its own guardrail —
            # nothing safe exists to synthesize, so the merged answer is
            # blocked too, same message as any other blocked answer.
            return FederatedResult(
                answer=BLOCKED_MESSAGE,
                sources=[],
                confidence=None,
                duration_ms=(time.monotonic() - start) * 1000,
                blocked=True,
                block_reason=succeeded[0].state["block_reason"],
                domains_used=domains,
                partial=partial,
            )

        partial = partial or len(answerable) < len(succeeded)
        domain_answers = [(run.domain, run.state["answer"]) for run in answerable]

        try:
            merged_answer = await synthesize_answers(question, domain_answers, partial)
        except (CircuitOpenError, OpenAIError):
            logger.error(
                "Synthesis unavailable", extra={"correlation_id": get_correlation_id()}
            )
            raise RetrievalUnavailableError("Synthesis unavailable") from None

        context_chunks = [
            chunk.text for run in answerable for chunk in run.state["reranked_chunks"]
        ] + [snippet for run in answerable for snippet in run.state["graph_context"]]

        (moderation_flagged, moderation_available), (injection_flagged, injection_available) = (
            await asyncio.gather(
                self._single._check_moderation_safely(merged_answer),
                self._single._check_injection_safely(question, merged_answer, context_chunks),
            )
        )

        duration_ms = (time.monotonic() - start) * 1000
        sources = [source for run in answerable for source in run.sources]

        if not moderation_available and not injection_available:
            return FederatedResult(
                answer=BLOCKED_MESSAGE,
                sources=[],
                confidence=None,
                duration_ms=duration_ms,
                blocked=True,
                block_reason="guardrails_unavailable",
                domains_used=domains,
                partial=partial,
            )

        if moderation_flagged or injection_flagged:
            reason = "moderation" if moderation_flagged else "injection"
            return FederatedResult(
                answer=BLOCKED_MESSAGE,
                sources=[],
                confidence=None,
                duration_ms=duration_ms,
                blocked=True,
                block_reason=reason,
                domains_used=domains,
                partial=partial,
            )

        return FederatedResult(
            answer=merged_answer,
            sources=sources,
            # No single well-defined relevance score exists once multiple
            # domains' reranked results have been merged into prose by an
            # LLM — reporting one of the per-domain scores would imply a
            # precision that isn't real.
            confidence=None,
            duration_ms=duration_ms,
            blocked=False,
            block_reason=None,
            domains_used=[run.domain for run in answerable],
            partial=partial,
        )

    async def _run_one_domain_safely(
        self, question: str, user_id: str, domain: str
    ) -> _DomainRun | None:
        """Run one domain's full retrieval pass; on failure, exclude it rather than raising.

        This is this feature's task-level equivalent of a per-domain
        circuit breaker (see ADR-040): a failing domain's exception is
        caught right here so it can't stop the other domains' concurrent
        asyncio.gather calls, and synthesis proceeds with whichever
        domains actually came back, marked partial.
        """
        try:
            state = await self._single.run_query(question, user_id, domain)
        except (CircuitOpenError, RetrievalUnavailableError, OpenAIError):
            logger.error(
                "Domain '%s' retrieval failed, excluding it from synthesis",
                domain,
                extra={"correlation_id": get_correlation_id()},
            )
            return None
        sources, _ = await self._single.build_sources_and_confidence(state)
        return _DomainRun(domain=domain, state=state, sources=sources)
