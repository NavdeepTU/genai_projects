from unittest.mock import AsyncMock, patch

import pytest

from app.core.circuit_breaker import CircuitOpenError
from app.repositories.graph_repository import GraphRepository


class _FakeResult:
    """Stands in for Neo4j's own async result iterator: `async for record in result`."""

    def __init__(self, records: list[dict]) -> None:
        self._records = records

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for record in self._records:
            yield record


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


async def test_create_reference_runs_a_merge_query_with_both_document_ids():
    """MERGE, not CREATE, throughout (see the method's own docstring) — running
    this twice for the same pair must stay safe, so the query text itself is
    part of what this test guards, not just that some query ran.
    """
    session = AsyncMock()
    repository = GraphRepository(session)

    await repository.create_reference("doc-1", "doc-2")

    session.run.assert_awaited_once()
    query, kwargs = session.run.call_args.args[0], session.run.call_args.kwargs
    assert "MERGE" in query
    assert "REFERENCES" in query
    assert "CREATE" not in query
    assert kwargs == {"source_id": "doc-1", "target_id": "doc-2"}


async def test_create_reference_propagates_a_circuit_open_error():
    session = AsyncMock()
    repository = GraphRepository(session)

    with (
        patch(
            "app.repositories.graph_repository.circuit_breaker.call",
            new=AsyncMock(side_effect=CircuitOpenError("neo4j is down")),
        ),
        pytest.raises(CircuitOpenError),
    ):
        await repository.create_reference("doc-1", "doc-2")


async def test_get_referenced_documents_returns_the_target_ids():
    session = AsyncMock()
    session.run = AsyncMock(return_value=_FakeResult([{"id": "doc-2"}, {"id": "doc-3"}]))
    repository = GraphRepository(session)

    result = await repository.get_referenced_documents("doc-1")

    assert result == ["doc-2", "doc-3"]
    query, kwargs = session.run.call_args.args[0], session.run.call_args.kwargs
    assert "REFERENCES" in query
    assert kwargs == {"document_id": "doc-1"}


async def test_get_referenced_documents_returns_an_empty_list_when_nothing_is_referenced():
    session = AsyncMock()
    session.run = AsyncMock(return_value=_FakeResult([]))
    repository = GraphRepository(session)

    result = await repository.get_referenced_documents("doc-1")

    assert result == []


async def test_get_referenced_documents_propagates_a_circuit_open_error():
    session = AsyncMock()
    repository = GraphRepository(session)

    with (
        patch(
            "app.repositories.graph_repository.circuit_breaker.call",
            new=AsyncMock(side_effect=CircuitOpenError("neo4j is down")),
        ),
        pytest.raises(CircuitOpenError),
    ):
        await repository.get_referenced_documents("doc-1")
