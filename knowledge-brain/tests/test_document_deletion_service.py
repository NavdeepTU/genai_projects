import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.core.circuit_breaker import CircuitOpenError
from app.services.document_deletion_service import DocumentDeletionService


def _document(storage_path: str | None = "doc-1.pdf"):
    document = AsyncMock()
    document.id = uuid.uuid4()
    document.storage_path = storage_path
    return document


def _service():
    repository = AsyncMock()
    graph_repository = AsyncMock()
    return DocumentDeletionService(repository, graph_repository), repository, graph_repository


async def test_delete_document_removes_the_blob_the_graph_node_and_the_row():
    service, repository, graph_repository = _service()
    document = _document(storage_path="doc-1.pdf")

    with patch(
        "app.services.document_deletion_service.delete_document_blob", new=AsyncMock()
    ) as mock_delete_blob:
        await service.delete_document(document)

    mock_delete_blob.assert_awaited_once_with("doc-1.pdf")
    graph_repository.delete_document_node.assert_awaited_once_with(str(document.id))
    repository.delete_document.assert_awaited_once_with(document)


async def test_delete_document_skips_the_blob_when_none_was_ever_stored():
    service, repository, graph_repository = _service()
    document = _document(storage_path=None)

    with patch(
        "app.services.document_deletion_service.delete_document_blob",
        new=AsyncMock(side_effect=AssertionError("should never be called")),
    ):
        await service.delete_document(document)

    graph_repository.delete_document_node.assert_awaited_once_with(str(document.id))
    repository.delete_document.assert_awaited_once_with(document)


async def test_delete_document_still_deletes_the_row_when_the_blob_delete_fails():
    """Blob Storage being briefly unreachable shouldn't block deleting the document."""
    service, repository, graph_repository = _service()
    document = _document(storage_path="doc-1.pdf")

    with patch(
        "app.services.document_deletion_service.delete_document_blob",
        new=AsyncMock(side_effect=CircuitOpenError("blob storage is down")),
    ):
        await service.delete_document(document)

    graph_repository.delete_document_node.assert_awaited_once_with(str(document.id))
    repository.delete_document.assert_awaited_once_with(document)


async def test_delete_document_still_deletes_the_row_when_the_graph_delete_fails():
    """Neo4j being briefly unreachable shouldn't block deleting the document either."""
    service, repository, graph_repository = _service()
    document = _document(storage_path="doc-1.pdf")
    graph_repository.delete_document_node = AsyncMock(side_effect=CircuitOpenError("neo4j is down"))

    with patch("app.services.document_deletion_service.delete_document_blob", new=AsyncMock()):
        await service.delete_document(document)

    repository.delete_document.assert_awaited_once_with(document)


async def test_delete_document_propagates_a_database_failure():
    """Unlike blob/graph cleanup, the database delete is the one part that must actually succeed."""
    service, repository, _ = _service()
    document = _document(storage_path=None)
    repository.delete_document = AsyncMock(side_effect=RuntimeError("db is down"))

    with pytest.raises(RuntimeError):
        await service.delete_document(document)
