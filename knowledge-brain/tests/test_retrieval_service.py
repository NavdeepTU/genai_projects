import uuid
from unittest.mock import AsyncMock, patch

from openai import OpenAIError

from app.core.circuit_breaker import CircuitOpenError
from app.models.document import Chunk
from app.repositories.document_repository import DocumentRepository
from app.services.retrieval_service import BLOCKED_ANSWER_MESSAGE, RetrievalService


async def test_build_sources_and_confidence_includes_filename_and_score(db_session):
    """Each reranked chunk should become a source carrying its own document's filename."""
    repository = DocumentRepository(db_session)
    document = await repository.create_document("policy.pdf")
    service = RetrievalService(repository, graph_repository=None)

    state = {
        "reranked_chunks": [
            Chunk(document_id=document.id, chunk_index=0, text="first relevant chunk"),
            Chunk(document_id=document.id, chunk_index=1, text="second relevant chunk"),
        ],
        "reranker_unavailable": False,
        "top_relevance_score": 0.83,
        "blocked": False,
    }

    sources, confidence = await service.build_sources_and_confidence(state)

    assert [s.chunk_text for s in sources] == ["first relevant chunk", "second relevant chunk"]
    assert all(s.filename == "policy.pdf" for s in sources)
    assert all(s.document_id == document.id for s in sources)
    assert confidence == 0.83


async def test_build_sources_and_confidence_dedupes_filename_lookups(db_session):
    """Two chunks from the same document should only need one filename lookup, not two."""
    repository = DocumentRepository(db_session)
    document = await repository.create_document("handbook.txt")
    service = RetrievalService(repository, graph_repository=None)

    lookups = []
    original_get_by_id = repository.get_by_id

    async def counting_get_by_id(document_id):
        lookups.append(document_id)
        return await original_get_by_id(document_id)

    repository.get_by_id = counting_get_by_id

    state = {
        "reranked_chunks": [
            Chunk(document_id=document.id, chunk_index=0, text="chunk one"),
            Chunk(document_id=document.id, chunk_index=1, text="chunk two"),
        ],
        "reranker_unavailable": False,
        "top_relevance_score": 0.5,
        "blocked": False,
    }

    await service.build_sources_and_confidence(state)

    assert lookups == [document.id]


async def test_build_sources_and_confidence_confidence_is_none_when_reranker_unavailable(db_session):
    """A fallback-ranked answer must never report a real-looking confidence number."""
    repository = DocumentRepository(db_session)
    document = await repository.create_document("notes.txt")
    service = RetrievalService(repository, graph_repository=None)

    state = {
        "reranked_chunks": [Chunk(document_id=document.id, chunk_index=0, text="fallback chunk")],
        "reranker_unavailable": True,
        # A real value on purpose — it must be ignored, not just happen to be falsy.
        "top_relevance_score": 0.91,
        "blocked": False,
    }

    _, confidence = await service.build_sources_and_confidence(state)

    assert confidence is None


async def test_build_sources_and_confidence_handles_missing_document(db_session):
    """A chunk referencing a document that no longer exists shouldn't crash the response."""
    repository = DocumentRepository(db_session)
    service = RetrievalService(repository, graph_repository=None)

    state = {
        "reranked_chunks": [Chunk(document_id=uuid.uuid4(), chunk_index=0, text="orphaned chunk")],
        "reranker_unavailable": False,
        "top_relevance_score": 0.6,
        "blocked": False,
    }

    sources, _ = await service.build_sources_and_confidence(state)

    assert sources[0].filename == "Unknown document"


async def test_build_sources_and_confidence_returns_nothing_when_blocked(db_session):
    """A blocked answer must never show the sources that tripped the guardrail."""
    repository = DocumentRepository(db_session)
    document = await repository.create_document("secret.txt")
    service = RetrievalService(repository, graph_repository=None)

    state = {
        "reranked_chunks": [Chunk(document_id=document.id, chunk_index=0, text="flagged chunk")],
        "reranker_unavailable": False,
        "top_relevance_score": 0.9,
        "blocked": True,
    }

    sources, confidence = await service.build_sources_and_confidence(state)

    assert sources == []
    assert confidence is None


def _guardrail_state(**overrides) -> dict:
    state = {
        "original_question": "What's the wifi password?",
        "answer": "The wifi password is hunter2.",
        "reranked_chunks": [],
        "graph_context": [],
    }
    state.update(overrides)
    return state


async def test_guardrail_node_allows_a_clean_answer(db_session):
    service = RetrievalService(DocumentRepository(db_session), graph_repository=None)

    with (
        patch("app.services.retrieval_service.check_moderation", new=AsyncMock(return_value=False)),
        patch("app.services.retrieval_service.check_injection", new=AsyncMock(return_value=False)),
    ):
        result = await service._guardrail_node(_guardrail_state())

    assert result["blocked"] is False
    assert result["block_reason"] is None


async def test_guardrail_node_blocks_when_moderation_flags(db_session):
    service = RetrievalService(DocumentRepository(db_session), graph_repository=None)

    with (
        patch("app.services.retrieval_service.check_moderation", new=AsyncMock(return_value=True)),
        patch("app.services.retrieval_service.check_injection", new=AsyncMock(return_value=False)),
    ):
        result = await service._guardrail_node(_guardrail_state())

    assert result["blocked"] is True
    assert result["block_reason"] == "moderation"
    assert result["answer"] == BLOCKED_ANSWER_MESSAGE


async def test_guardrail_node_blocks_when_injection_flags(db_session):
    service = RetrievalService(DocumentRepository(db_session), graph_repository=None)

    with (
        patch("app.services.retrieval_service.check_moderation", new=AsyncMock(return_value=False)),
        patch("app.services.retrieval_service.check_injection", new=AsyncMock(return_value=True)),
    ):
        result = await service._guardrail_node(_guardrail_state())

    assert result["blocked"] is True
    assert result["block_reason"] == "injection"
    assert result["answer"] == BLOCKED_ANSWER_MESSAGE


async def test_guardrail_node_allows_when_one_check_is_down_and_the_other_is_clean(db_session):
    """A single check's own outage shouldn't block an answer the other check actually cleared."""
    service = RetrievalService(DocumentRepository(db_session), graph_repository=None)

    with (
        patch(
            "app.services.retrieval_service.check_moderation",
            new=AsyncMock(side_effect=CircuitOpenError("moderation is down")),
        ),
        patch("app.services.retrieval_service.check_injection", new=AsyncMock(return_value=False)),
    ):
        result = await service._guardrail_node(_guardrail_state())

    assert result["blocked"] is False


async def test_guardrail_node_blocks_when_the_other_check_is_down_but_this_one_flags(db_session):
    """A real flag from the check that's still up must still block, even with the other down."""
    service = RetrievalService(DocumentRepository(db_session), graph_repository=None)

    with (
        patch(
            "app.services.retrieval_service.check_moderation",
            new=AsyncMock(side_effect=OpenAIError("moderation errored")),
        ),
        patch("app.services.retrieval_service.check_injection", new=AsyncMock(return_value=True)),
    ):
        result = await service._guardrail_node(_guardrail_state())

    assert result["blocked"] is True
    assert result["block_reason"] == "injection"


async def test_guardrail_node_blocks_when_both_checks_are_down(db_session):
    """No signal at all is treated as unsafe — a clean answer proven safe by nothing isn't checked."""
    service = RetrievalService(DocumentRepository(db_session), graph_repository=None)

    with (
        patch(
            "app.services.retrieval_service.check_moderation",
            new=AsyncMock(side_effect=CircuitOpenError("moderation is down")),
        ),
        patch(
            "app.services.retrieval_service.check_injection",
            new=AsyncMock(side_effect=CircuitOpenError("injection check is down")),
        ),
    ):
        result = await service._guardrail_node(_guardrail_state())

    assert result["blocked"] is True
    assert result["block_reason"] == "guardrails_unavailable"
