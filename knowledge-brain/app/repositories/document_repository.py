import logging
import uuid

from sqlalchemy import func, select
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

    async def find_similar_chunks(self, query_embedding: list[float], limit: int = 5) -> list[Chunk]:
        """Return the chunks whose embeddings are closest to a query vector.

        `cosine_distance` returns 0 for identical direction and larger
        values for less similar vectors, so ordering ascending and
        taking the first few gives us the most relevant chunks first.
        """
        stmt = (
            select(Chunk)
            .order_by(Chunk.embedding.cosine_distance(query_embedding))
            .limit(limit)
        )
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to search for similar chunks")
            raise
        return list(result.scalars().all())

    async def find_by_keyword(self, query: str, limit: int = 5) -> list[Chunk]:
        """Return the chunks that best match a query via Postgres full-text search.

        Both the chunk text and the query are normalized the same way
        (lowercased, stop words removed, words stemmed to their root) by
        `to_tsvector`/`plainto_tsquery` before comparing, and `ts_rank`
        scores how well each match is, not just whether one exists.
        """
        tsquery = func.plainto_tsquery("english", query)
        tsvector = func.to_tsvector("english", Chunk.text)

        stmt = (
            select(Chunk)
            .where(tsvector.op("@@")(tsquery))
            .order_by(func.ts_rank(tsvector, tsquery).desc())
            .limit(limit)
        )
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to search for chunks by keyword")
            raise
        return list(result.scalars().all())

    async def get_first_chunk_text(self, document_id: uuid.UUID) -> str | None:
        """Return a referenced document's first chunk as a representative snippet.

        Used for graph context, not primary retrieval, so one chunk is
        enough to give the LLM a sense of what the referenced document
        is about, without pulling in its full text.
        """
        stmt = (
            select(Chunk.text)
            .where(Chunk.document_id == document_id)
            .order_by(Chunk.chunk_index)
            .limit(1)
        )
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to fetch first chunk for document %s", document_id)
            raise
        return result.scalar_one_or_none()

    async def rollback(self) -> None:
        """Clear an aborted transaction so later queries on this session can run.

        Postgres refuses any further queries on a session after one fails,
        until the transaction is explicitly rolled back — needed when the
        caller wants to catch a failed search and try a different one on
        the same session right after.
        """
        await self.session.rollback()

    def detach(self, chunks: list[Chunk]) -> None:
        """Detach already-fetched chunks from the session.

        A rollback() (see above) invalidates every object still tracked
        by the session, including ones from an *earlier*, successful
        query — the next access to one of their columns would trigger a
        surprise database round-trip to reload it, which isn't safe
        outside an awaited call and raises instead. Detaching a chunk
        right after fetching it keeps its already-loaded data usable
        even if something else rolls the session back later.
        """
        for chunk in chunks:
            self.session.expunge(chunk)
