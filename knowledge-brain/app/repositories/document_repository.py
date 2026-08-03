import logging
import uuid

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Chunk, Document, DocumentStatus

logger = logging.getLogger(__name__)


class DocumentRepository:
    """All direct database access for documents and chunks lives here.

    Services call these methods instead of writing queries themselves,
    so query logic stays in one place, and can be swapped or tested
    independently of business logic.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_document(self, filename: str) -> Document:
        """Insert a new document row (status defaults to pending)."""
        document = Document(filename=filename)
        self.session.add(document)
        try:
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to create document row for %s", filename)
            raise
        await self.session.refresh(document)
        return document

    async def save_chunks(self, chunks: list[Chunk]) -> None:
        """Insert many chunk rows, each with its own embedding, at once."""
        self.session.add_all(chunks)
        try:
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to save %d chunks", len(chunks))
            raise

    async def update_status(self, document_id: uuid.UUID, status: DocumentStatus) -> None:
        """Move a document to a new pipeline stage, e.g. ready or failed."""
        document = await self.session.get(Document, document_id)
        if document is None:
            raise ValueError(f"Document {document_id} not found")

        document.status = status
        try:
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to update status for document %s", document_id)
            raise
