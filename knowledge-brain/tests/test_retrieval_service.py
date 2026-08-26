import uuid

from app.models.document import Chunk
from app.repositories.document_repository import DocumentRepository
from app.services.retrieval_service import RetrievalService


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
    }

    sources, _ = await service.build_sources_and_confidence(state)

    assert sources[0].filename == "Unknown document"
