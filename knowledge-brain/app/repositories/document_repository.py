import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Chunk, Document, DocumentStatus
from app.models.document_permission import DocumentPermission

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

    async def flag_for_review(self, document_id: uuid.UUID) -> None:
        """Stop a document short of embedding: hold it for human review of PII found.

        Sets both the status and the permanent pii_detected flag in one
        update, since reaching this state always means both happened
        together — unlike update_status, which only ever changes status.
        """
        document = await self.session.get(Document, document_id)
        if document is None:
            raise ValueError(f"Document {document_id} not found")

        document.status = DocumentStatus.PENDING_REVIEW
        document.pii_detected = True
        try:
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to flag document %s for review", document_id)
            raise

    async def mark_failed(self, document_id: uuid.UUID, reason: str) -> None:
        """Mark a document failed, recording why.

        An extraction bug and an Azure outage should be distinguishable
        later by reading the row, not both just collapse into "failed"
        with no way to tell them apart.
        """
        document = await self.session.get(Document, document_id)
        if document is None:
            raise ValueError(f"Document {document_id} not found")

        document.status = DocumentStatus.FAILED
        document.failure_reason = reason
        try:
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to mark document %s failed", document_id)
            raise

    async def find_similar_chunks(
        self, query_embedding: list[float], user_id: str, limit: int = 5
    ) -> list[Chunk]:
        """Return the chunks whose embeddings are closest to a query vector.

        `cosine_distance` returns 0 for identical direction and larger
        values for less similar vectors, so ordering ascending and
        taking the first few gives us the most relevant chunks first.
        Joined against document_permissions so only chunks from documents
        this user can access are ever candidates — filtered before the
        ranking and the limit, not after, so an inaccessible chunk can
        never take a slot in the results a promotable one should've had.
        """
        stmt = (
            select(Chunk)
            .join(DocumentPermission, DocumentPermission.document_id == Chunk.document_id)
            .where(DocumentPermission.user_id == user_id)
            .order_by(Chunk.embedding.cosine_distance(query_embedding))
            .limit(limit)
        )
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to search for similar chunks")
            raise
        return list(result.scalars().all())

    async def find_by_keyword(self, query: str, user_id: str, limit: int = 5) -> list[Chunk]:
        """Return the chunks that best match a query via Postgres full-text search.

        Both the chunk text and the query are normalized the same way
        (lowercased, stop words removed, words stemmed to their root) by
        `to_tsvector`/`plainto_tsquery` before comparing, and `ts_rank`
        scores how well each match is, not just whether one exists. Same
        permission join as find_similar_chunks, same reasoning: filtered
        before ranking, not after.
        """
        tsquery = func.plainto_tsquery("english", query)
        tsvector = func.to_tsvector("english", Chunk.text)

        stmt = (
            select(Chunk)
            .join(DocumentPermission, DocumentPermission.document_id == Chunk.document_id)
            .where(tsvector.op("@@")(tsquery), DocumentPermission.user_id == user_id)
            .order_by(func.ts_rank(tsvector, tsquery).desc())
            .limit(limit)
        )
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to search for chunks by keyword")
            raise
        return list(result.scalars().all())

    async def find_by_keyword_unrestricted(self, query: str, limit: int = 5) -> list[Chunk]:
        """Same search as find_by_keyword, deliberately with no permission filter.

        For internal, system-level use only — building the Neo4j reference
        graph at ingestion time, which asks "does any document define this
        term" as a fact about the documents themselves, not "what can this
        particular user see." Never call this on behalf of a user-facing
        request; every caller answering a real question must use
        find_by_keyword instead.
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
            logger.exception("Failed to search for chunks by keyword (unrestricted)")
            raise
        return list(result.scalars().all())

    async def get_document_by_filename(self, filename: str) -> Document | None:
        """Return the most recently uploaded ready document with this filename, if any.

        Used by the evaluation harness to avoid re-ingesting its fixture
        documents on every run — not part of the normal upload flow.
        """
        stmt = (
            select(Document)
            .where(Document.filename == filename, Document.status == DocumentStatus.READY)
            .order_by(Document.uploaded_at.desc())
            .limit(1)
        )
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to look up document by filename %s", filename)
            raise
        return result.scalar_one_or_none()

    async def list_documents_for_user(self, user_id: str) -> list[Document]:
        """Return every document this user has been granted access to, newest first.

        Same permission join as find_by_keyword/find_similar_chunks — a
        document with no matching document_permissions row for this user
        never appears, the same rule applied to browsing instead of search.
        """
        stmt = (
            select(Document)
            .join(DocumentPermission, DocumentPermission.document_id == Document.id)
            .where(DocumentPermission.user_id == user_id)
            .order_by(Document.uploaded_at.desc())
        )
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to list documents for user %s", user_id)
            raise
        return list(result.scalars().all())

    async def get_first_chunk_text(self, document_id: uuid.UUID, user_id: str) -> str | None:
        """Return a referenced document's first chunk as a representative snippet.

        Used for graph context, not primary retrieval, so one chunk is
        enough to give the LLM a sense of what the referenced document
        is about, without pulling in its full text. Same permission join
        as every other retrieval path — a document being *referenced* by
        one this user can see doesn't mean this user can see it too, and
        without this filter that's exactly how confidential content could
        leak into an answer through the graph-context feature.
        """
        stmt = (
            select(Chunk.text)
            .join(DocumentPermission, DocumentPermission.document_id == Chunk.document_id)
            .where(Chunk.document_id == document_id, DocumentPermission.user_id == user_id)
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
