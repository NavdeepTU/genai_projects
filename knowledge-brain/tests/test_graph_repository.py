from unittest.mock import AsyncMock, patch

import pytest

from app.core.circuit_breaker import CircuitOpenError
from app.repositories.graph_repository import GraphRepository

# GraphRepository.create_reference and get_referenced_documents are covered
# only indirectly (through DocumentGraphService/ingestion) — a pre-existing,
# named gap (see README's "Known gaps"). delete_document_node is tested
# directly here since it's new, with no existing indirect coverage anywhere.


async def test_delete_document_node_runs_a_detach_delete():
    session = AsyncMock()
    repository = GraphRepository(session)

    await repository.delete_document_node("doc-1")

    session.run.assert_awaited_once()
    query, kwargs = session.run.call_args.args[0], session.run.call_args.kwargs
    assert "DETACH DELETE" in query
    assert kwargs == {"document_id": "doc-1"}


async def test_delete_document_node_propagates_a_circuit_open_error():
    """When Neo4j's own circuit is open, the caller (DocumentDeletionService)
    is the one that decides this is best-effort — this repository method
    itself must not swallow the error.
    """
    session = AsyncMock()
    repository = GraphRepository(session)

    with (
        patch(
            "app.repositories.graph_repository.circuit_breaker.call",
            new=AsyncMock(side_effect=CircuitOpenError("neo4j is down")),
        ),
        pytest.raises(CircuitOpenError),
    ):
        await repository.delete_document_node("doc-1")
