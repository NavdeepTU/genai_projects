from unittest.mock import AsyncMock, patch

import pytest

from app.core.circuit_breaker import CircuitOpenError
from app.services.federated_retrieval_service import FederatedRetrievalService
from app.services.retrieval_service import BLOCKED_MESSAGE, RetrievalUnavailableError


class _FakeRepository:
    """Just enough of DocumentRepository for the classification step to run."""

    def __init__(self, domains: list[str]) -> None:
        self._domains = domains

    async def list_domains_for_user(self, user_id: str) -> list[str]:
        return self._domains


def _state(answer: str, *, blocked: bool = False, block_reason: str | None = None) -> dict:
    return {
        "answer": answer,
        "blocked": blocked,
        "block_reason": block_reason,
        "reranked_chunks": [],
        "graph_context": [],
        "reranker_unavailable": False,
        "top_relevance_score": 0.0,
    }


def _service(domains: list[str]) -> FederatedRetrievalService:
    return FederatedRetrievalService(_FakeRepository(domains), graph_repository=None)


async def test_skips_classification_when_user_has_no_domains():
    """A user with no domain-tagged documents at all shouldn't pay for a classification call."""
    service = _service([])
    service._single.run_query = AsyncMock(return_value=_state("an answer"))

    with patch(
        "app.services.federated_retrieval_service.classify_domains",
        new=AsyncMock(side_effect=AssertionError("should never be called")),
    ):
        result = await service.run_query("What's our vacation policy?", "user-1")

    assert result.domains_used == []
    service._single.run_query.assert_awaited_once_with("What's our vacation policy?", "user-1", None)


async def test_single_domain_delegates_straight_to_retrieval_service():
    """Exactly one domain needed should behave like the plain single-domain pipeline."""
    service = _service(["HR"])
    service._single.run_query = AsyncMock(return_value=_state("HR's answer"))

    with patch(
        "app.services.federated_retrieval_service.classify_domains",
        new=AsyncMock(return_value=["HR"]),
    ):
        result = await service.run_query("What's the leave policy?", "user-1")

    assert result.answer == "HR's answer"
    assert result.domains_used == ["HR"]
    service._single.run_query.assert_awaited_once_with("What's the leave policy?", "user-1", "HR")


async def test_falls_back_to_unrestricted_search_when_classification_unavailable():
    """A down classifier shouldn't block answering — just search everything, like before this feature."""
    service = _service(["HR", "Finance"])
    service._single.run_query = AsyncMock(return_value=_state("an answer"))

    with patch(
        "app.services.federated_retrieval_service.classify_domains",
        new=AsyncMock(side_effect=CircuitOpenError("classifier is down")),
    ):
        result = await service.run_query("some question", "user-1")

    assert result.domains_used == []
    service._single.run_query.assert_awaited_once_with("some question", "user-1", None)


async def test_two_domains_run_concurrently_and_get_synthesized():
    service = _service(["HR", "Finance"])

    async def fake_run_query(question, user_id, domain=None):
        return _state(f"{domain}'s draft answer")

    service._single.run_query = AsyncMock(side_effect=fake_run_query)
    service._single._check_moderation_safely = AsyncMock(return_value=(False, True))
    service._single._check_injection_safely = AsyncMock(return_value=(False, True))

    with (
        patch(
            "app.services.federated_retrieval_service.classify_domains",
            new=AsyncMock(return_value=["HR", "Finance"]),
        ),
        patch(
            "app.services.federated_retrieval_service.synthesize_answers",
            new=AsyncMock(return_value="merged answer"),
        ) as mock_synthesize,
    ):
        result = await service.run_query("a cross-domain question", "user-1")

    assert result.answer == "merged answer"
    assert result.blocked is False
    assert result.confidence is None
    assert result.partial is False
    assert sorted(result.domains_used) == ["Finance", "HR"]
    domain_answers = mock_synthesize.call_args.args[1]
    assert set(domain_answers) == {("HR", "HR's draft answer"), ("Finance", "Finance's draft answer")}


async def test_a_failing_domain_is_excluded_and_marks_the_result_partial():
    service = _service(["HR", "Finance"])

    async def fake_run_query(question, user_id, domain=None):
        if domain == "Finance":
            raise RetrievalUnavailableError("both searches failed")
        return _state("HR's draft answer")

    service._single.run_query = AsyncMock(side_effect=fake_run_query)
    service._single._check_moderation_safely = AsyncMock(return_value=(False, True))
    service._single._check_injection_safely = AsyncMock(return_value=(False, True))

    with (
        patch(
            "app.services.federated_retrieval_service.classify_domains",
            new=AsyncMock(return_value=["HR", "Finance"]),
        ),
        patch(
            "app.services.federated_retrieval_service.synthesize_answers",
            new=AsyncMock(return_value="merged answer, missing Finance"),
        ) as mock_synthesize,
    ):
        result = await service.run_query("a cross-domain question", "user-1")

    assert result.partial is True
    assert result.domains_used == ["HR"]
    assert mock_synthesize.call_args.args[2] is True  # partial flag passed to synthesis


async def test_raises_when_every_domain_fails():
    service = _service(["HR", "Finance"])
    service._single.run_query = AsyncMock(side_effect=RetrievalUnavailableError("down"))

    with (
        patch(
            "app.services.federated_retrieval_service.classify_domains",
            new=AsyncMock(return_value=["HR", "Finance"]),
        ),
        pytest.raises(RetrievalUnavailableError),
    ):
        await service.run_query("a cross-domain question", "user-1")


async def test_blocks_when_every_answerable_domain_was_itself_blocked():
    """If every domain that came back was blocked by its own guardrail, nothing safe exists to merge."""
    service = _service(["HR", "Finance"])

    async def fake_run_query(question, user_id, domain=None):
        return _state(BLOCKED_MESSAGE, blocked=True, block_reason="jailbreak")

    service._single.run_query = AsyncMock(side_effect=fake_run_query)

    with (
        patch(
            "app.services.federated_retrieval_service.classify_domains",
            new=AsyncMock(return_value=["HR", "Finance"]),
        ),
        patch(
            "app.services.federated_retrieval_service.synthesize_answers",
            new=AsyncMock(side_effect=AssertionError("should never be called")),
        ),
    ):
        result = await service.run_query("a bad question", "user-1")

    assert result.blocked is True
    assert result.block_reason == "jailbreak"
    assert result.answer == BLOCKED_MESSAGE


async def test_blocks_the_synthesized_answer_when_it_flags_moderation():
    service = _service(["HR", "Finance"])
    service._single.run_query = AsyncMock(
        side_effect=lambda q, u, domain=None: _state(f"{domain}'s draft answer")
    )
    service._single._check_moderation_safely = AsyncMock(return_value=(True, True))
    service._single._check_injection_safely = AsyncMock(return_value=(False, True))

    with (
        patch(
            "app.services.federated_retrieval_service.classify_domains",
            new=AsyncMock(return_value=["HR", "Finance"]),
        ),
        patch(
            "app.services.federated_retrieval_service.synthesize_answers",
            new=AsyncMock(return_value="merged answer"),
        ),
    ):
        result = await service.run_query("a cross-domain question", "user-1")

    assert result.blocked is True
    assert result.block_reason == "moderation"
    assert result.answer == BLOCKED_MESSAGE


async def test_blocks_the_synthesized_answer_when_both_safety_checks_are_down():
    service = _service(["HR", "Finance"])
    service._single.run_query = AsyncMock(
        side_effect=lambda q, u, domain=None: _state(f"{domain}'s draft answer")
    )
    service._single._check_moderation_safely = AsyncMock(return_value=(False, False))
    service._single._check_injection_safely = AsyncMock(return_value=(False, False))

    with (
        patch(
            "app.services.federated_retrieval_service.classify_domains",
            new=AsyncMock(return_value=["HR", "Finance"]),
        ),
        patch(
            "app.services.federated_retrieval_service.synthesize_answers",
            new=AsyncMock(return_value="merged answer"),
        ),
    ):
        result = await service.run_query("a cross-domain question", "user-1")

    assert result.blocked is True
    assert result.block_reason == "guardrails_unavailable"
