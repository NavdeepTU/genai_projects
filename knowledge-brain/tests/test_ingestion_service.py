from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.document import Chunk, Document, DocumentStatus
from app.repositories.document_repository import DocumentRepository
from app.repositories.permission_repository import PermissionRepository
from app.services.ingestion_service import IngestionService


async def test_ingest_document_succeeds(db_session):
    """A .txt upload should end up ready, with its text saved as a chunk."""
    repository = DocumentRepository(db_session)
    service = IngestionService(repository, PermissionRepository(db_session))
    fake_embedding = [0.1] * 1536

    document = await service.create_document("notes.txt", "test-user")
    with (
        patch("app.services.ingestion_service.detect_pii", new=AsyncMock(return_value=[])),
        patch(
            "app.services.ingestion_service.embed_chunks",
            new=AsyncMock(return_value=[fake_embedding]),
        ),
    ):
        await service.process_document(document.id, "notes.txt", b"hello world")

    assert document.status == DocumentStatus.READY

    result = await db_session.execute(select(Chunk).where(Chunk.document_id == document.id))
    chunks = result.scalars().all()
    assert len(chunks) == 1
    assert chunks[0].text == "hello world"


async def test_create_document_stores_domains_and_still_grants_access(db_session):
    """domains flows through to the repository without breaking the existing access grant."""
    repository = DocumentRepository(db_session)
    permission_repository = PermissionRepository(db_session)
    service = IngestionService(repository, permission_repository)

    document = await service.create_document("handbook.pdf", "test-user", domains=["HR"])

    assert document.domains == ["HR"]
    assert await permission_repository.has_access(document.id, "test-user")


async def test_ingest_document_marks_failed_on_embedding_error(db_session):
    """If OpenAI fails, the document should end up failed, not stuck pending."""
    repository = DocumentRepository(db_session)
    service = IngestionService(repository, PermissionRepository(db_session))

    document = await service.create_document("notes.txt", "test-user")
    with (
        patch("app.services.ingestion_service.detect_pii", new=AsyncMock(return_value=[])),
        patch(
            "app.services.ingestion_service.embed_chunks",
            new=AsyncMock(side_effect=RuntimeError("OpenAI is down")),
        ),
        pytest.raises(RuntimeError),
    ):
        await service.process_document(document.id, "notes.txt", b"hello world")

    result = await db_session.execute(select(Document).where(Document.filename == "notes.txt"))
    refreshed = result.scalar_one()
    assert refreshed.status == DocumentStatus.FAILED
    assert refreshed.failure_reason == "RuntimeError: OpenAI is down"


async def test_ingest_document_flags_pii_for_review(db_session):
    """A document with PII should be held for review, never chunked or embedded."""
    repository = DocumentRepository(db_session)
    service = IngestionService(repository, PermissionRepository(db_session))

    document = await service.create_document("notes.txt", "test-user")
    with (
        patch(
            "app.services.ingestion_service.detect_pii",
            new=AsyncMock(return_value=["Person", "USSocialSecurityNumber"]),
        ),
        patch("app.services.ingestion_service.embed_chunks", new=AsyncMock()) as mock_embed,
    ):
        await service.process_document(document.id, "notes.txt", b"John Doe, SSN 123-45-6789")

    assert document.status == DocumentStatus.PENDING_REVIEW
    assert document.pii_detected is True
    mock_embed.assert_not_called()

    result = await db_session.execute(select(Chunk).where(Chunk.document_id == document.id))
    assert result.scalars().all() == []
