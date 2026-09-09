import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.document import Chunk, Document, DocumentStatus, ProcessingStage
from app.models.domain import Domain, document_domains
from app.models.user import User

logger = logging.getLogger(__name__)


class DocumentRepository:
    """All direct database access for documents and chunks lives here.

    Services call these methods instead of writing queries themselves,
    so query logic stays in one place, and can be swapped or tested
    independently of business logic.

    Since ADR-046, every document-scoped read here filters by
    `tenant_id`, not a per-user grant — a document is visible to every
    user in the tenant that uploaded it, full stop. There is no more
    per-document, per-user access list to check.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_document(
        self,
        filename: str,
        tenant_id: uuid.UUID,
        uploaded_by: uuid.UUID | None = None,
        domain_ids: list[uuid.UUID] | None = None,
    ) -> Document:
        """Insert a new document row (status defaults to pending), owned by one tenant.

        domain_ids is filtered down to only domains that actually belong
        to this tenant before linking — a stray or cross-tenant id is
        silently dropped, not rejected, the same "if it isn't yours, it
        doesn't exist" pattern this project's tenant isolation already
        uses everywhere else. uploaded_by is who this document is visible
        to exclusively while it's held for PII review (ADR-048) —
        optional since the evaluation harness has no real user account to
        attribute uploads to.
        """
        document = Document(filename=filename, tenant_id=tenant_id, uploaded_by=uploaded_by)
        if domain_ids:
            stmt = select(Domain).where(Domain.id.in_(domain_ids), Domain.tenant_id == tenant_id)
            result = await self.session.execute(stmt)
            document.domain_objects = list(result.scalars().all())
        self.session.add(document)
        try:
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to create document row for %s", filename)
            raise
        await self.session.refresh(document, attribute_names=["domain_objects"])
        return document

    async def set_storage_path(self, document_id: uuid.UUID, storage_path: str) -> None:
        """Record where a document's original file landed in Blob Storage (ADR-044)."""
        document = await self.session.get(Document, document_id)
        if document is None:
            raise ValueError(f"Document {document_id} not found")

        document.storage_path = storage_path
        try:
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to set storage path for document %s", document_id)
            raise

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

    async def update_processing_stage(self, document_id: uuid.UUID, stage: ProcessingStage) -> None:
        """Move a document to a new step within the processing pipeline."""
        document = await self.session.get(Document, document_id)
        if document is None:
            raise ValueError(f"Document {document_id} not found")

        document.processing_stage = stage
        try:
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to update processing stage for document %s", document_id)
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

    async def submit_for_review(self, document_id: uuid.UUID) -> None:
        """Move a held document into the admin review queue (ADR-048).

        The route layer, not this method, checks that the caller is
        actually allowed to submit this particular document (its own
        uploader, or an admin for a legacy document with no recorded
        uploader) and that it's currently PENDING_REVIEW — this method
        just performs the transition once that's already been decided.
        """
        document = await self.session.get(Document, document_id)
        if document is None:
            raise ValueError(f"Document {document_id} not found")

        document.status = DocumentStatus.IN_REVIEW
        try:
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to submit document %s for review", document_id)
            raise

    async def reject_document(self, document_id: uuid.UUID) -> None:
        """Move a document from IN_REVIEW to the terminal REJECTED state (ADR-048).

        Terminal on purpose — nothing in this codebase moves a document
        out of REJECTED again, matching the product decision that a
        rejected upload can't be resubmitted, only re-uploaded fresh.
        """
        document = await self.session.get(Document, document_id)
        if document is None:
            raise ValueError(f"Document {document_id} not found")

        document.status = DocumentStatus.REJECTED
        try:
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to reject document %s", document_id)
            raise

    async def list_review_queue_for_tenant(
        self, tenant_id: uuid.UUID
    ) -> list[tuple[Document, str | None]]:
        """Return every IN_REVIEW document in this tenant, with its uploader's email.

        Scoped to one tenant, not global (ADR-048) — an admin only ever
        reviews their own tenant's flagged content, never another
        tenant's, the same boundary every other document read in this
        system respects. The email is a left outer join since a legacy
        document's uploaded_by can be null.
        """
        stmt = (
            select(Document, User.email)
            .outerjoin(User, User.id == Document.uploaded_by)
            .where(Document.tenant_id == tenant_id, Document.status == DocumentStatus.IN_REVIEW)
            .order_by(Document.uploaded_at.asc())
        )
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to list review queue for tenant %s", tenant_id)
            raise
        return [(doc, email) for doc, email in result.all()]

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

    async def delete_document(self, document: Document) -> None:
        """Delete a document row — its chunks cascade with it (ADR-045).

        Takes the already-loaded Document, not an id, since the caller
        (DocumentDeletionService) already fetched it once via
        get_document_for_tenant for the permission check, and needs its
        storage_path *before* this call removes the row.
        """
        await self.session.delete(document)
        try:
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to delete document %s", document.id)
            raise

    async def find_similar_chunks(
        self,
        query_embedding: list[float],
        tenant_id: uuid.UUID,
        limit: int = 5,
        domain: str | None = None,
    ) -> list[Chunk]:
        """Return the chunks whose embeddings are closest to a query vector.

        `cosine_distance` returns 0 for identical direction and larger
        values for less similar vectors, so ordering ascending and
        taking the first few gives us the most relevant chunks first.
        Joined against documents so only chunks from this tenant's own
        documents are ever candidates (ADR-046) — filtered before the
        ranking and the limit, not after, so a chunk from another
        tenant's document can never take a slot in the results.
        `domain`, when given, narrows candidates further to documents
        tagged with that domain — the actual mechanism a domain-scoped
        retrieval agent uses to only see its own slice of the knowledge
        base (see FederatedRetrievalService). Omitted, this searches
        exactly as it always has: every document this tenant can access,
        regardless of domain.
        """
        stmt = (
            select(Chunk)
            .join(Document, Document.id == Chunk.document_id)
            .where(Document.tenant_id == tenant_id)
            .order_by(Chunk.embedding.cosine_distance(query_embedding))
            .limit(limit)
        )
        if domain is not None:
            stmt = stmt.where(Document.domain_objects.any(Domain.name == domain))
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to search for similar chunks")
            raise
        return list(result.scalars().all())

    async def find_by_keyword(
        self, query: str, tenant_id: uuid.UUID, limit: int = 5, domain: str | None = None
    ) -> list[Chunk]:
        """Return the chunks that best match a query via Postgres full-text search.

        Both the chunk text and the query are normalized the same way
        (lowercased, stop words removed, words stemmed to their root) by
        `to_tsvector`/`plainto_tsquery` before comparing, and `ts_rank`
        scores how well each match is, not just whether one exists. Same
        tenant filter as find_similar_chunks, same reasoning: filtered
        before ranking, not after. Same optional `domain` narrowing too.

        This also serves the one caller that used to need an
        "unrestricted" version (DocumentGraphService, building reference
        edges at ingestion time) — now that every user in a tenant can
        see every document in it, "everything this tenant's documents
        say" and "everything a specific user in that tenant can see" are
        the same set, so a separate unrestricted method would just
        duplicate this one.
        """
        tsquery = func.plainto_tsquery("english", query)
        tsvector = func.to_tsvector("english", Chunk.text)

        stmt = (
            select(Chunk)
            .join(Document, Document.id == Chunk.document_id)
            .where(tsvector.op("@@")(tsquery), Document.tenant_id == tenant_id)
            .order_by(func.ts_rank(tsvector, tsquery).desc())
            .limit(limit)
        )
        if domain is not None:
            stmt = stmt.where(Document.domain_objects.any(Domain.name == domain))
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to search for chunks by keyword")
            raise
        return list(result.scalars().all())

    async def list_domains_for_tenant(self, tenant_id: uuid.UUID) -> list[str]:
        """Return every distinct domain name currently tagged on this tenant's documents.

        The set the domain-classification supervisor actually chooses
        from — a domain this tenant has no documents in isn't a
        meaningful choice, so it's never even offered. An inner join
        against document_domains is what makes that filtering automatic:
        a registered-but-unused Domain row (see DomainRepository.list_for_tenant,
        which returns those too, for the admin panel and upload picker)
        simply never matches this join, and an untagged document
        contributes nothing either.
        """
        stmt = (
            select(Domain.name)
            .join(document_domains, document_domains.c.domain_id == Domain.id)
            .where(Domain.tenant_id == tenant_id)
            .distinct()
        )
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to list domains for tenant %s", tenant_id)
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

    async def list_documents_for_tenant(
        self, tenant_id: uuid.UUID, caller_id: uuid.UUID
    ) -> list[Document]:
        """Return every document this caller can see, newest first (ADR-046).

        A document held for PII review (PENDING_REVIEW, IN_REVIEW, or
        REJECTED) is the one exception to "every document in this tenant
        is visible to everyone in it" — it only shows up here for its own
        uploader, not the rest of the tenant, until an admin approves it
        and it becomes a normal, fully tenant-visible document (ADR-048).
        An admin reviewing someone else's flagged document does so
        through the dedicated review queue, not this list.
        """
        review_statuses = (
            DocumentStatus.PENDING_REVIEW,
            DocumentStatus.IN_REVIEW,
            DocumentStatus.REJECTED,
        )
        stmt = (
            select(Document)
            .options(selectinload(Document.domain_objects))
            .where(
                Document.tenant_id == tenant_id,
                (Document.status.not_in(review_statuses)) | (Document.uploaded_by == caller_id),
            )
            .order_by(Document.uploaded_at.desc())
        )
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to list documents for tenant %s", tenant_id)
            raise
        return list(result.scalars().all())

    async def count_documents_for_tenant(self, tenant_id: uuid.UUID) -> int:
        """Return how many documents this tenant can see, without fetching the rows.

        The dashboard only needs the number, and fetching every row just
        to call len() on it wastes a full, unnecessary transfer of every
        document's data.
        """
        stmt = select(func.count()).select_from(Document).where(Document.tenant_id == tenant_id)
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to count documents for tenant %s", tenant_id)
            raise
        return result.scalar_one()

    async def get_by_id(self, document_id: uuid.UUID) -> Document | None:
        """Return a document by id with no tenant check — internal use only.

        For system-level code (here, the background job deciding whether
        to build graph references) that isn't answering on behalf of a
        particular tenant. Never call this to serve a user-facing request.
        """
        return await self.session.get(Document, document_id)

    async def get_document_for_tenant(
        self, document_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Document | None:
        """Return one document if this tenant can see it, else None (ADR-046).

        Same tenant filter as list_documents_for_tenant — a document
        belonging to another tenant is invisible, whether someone is
        browsing the full list or polling one document directly by id.
        """
        stmt = select(Document).where(
            Document.id == document_id, Document.tenant_id == tenant_id
        )
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to fetch document %s for tenant %s", document_id, tenant_id)
            raise
        return result.scalar_one_or_none()

    async def get_first_chunk_text(self, document_id: uuid.UUID, tenant_id: uuid.UUID) -> str | None:
        """Return a referenced document's first chunk as a representative snippet.

        Used for graph context, not primary retrieval, so one chunk is
        enough to give the LLM a sense of what the referenced document
        is about, without pulling in its full text. Same tenant filter
        as every other retrieval path — a document being *referenced* by
        one this tenant can see doesn't mean this tenant can see it too
        (the reference itself could, in principle, point across a tenant
        boundary if the graph were ever built without tenant scoping —
        see DocumentGraphService, which is why it's scoped too), and
        without this filter that's exactly how confidential content
        could leak into an answer through the graph-context feature.
        """
        stmt = (
            select(Chunk.text)
            .join(Document, Document.id == Chunk.document_id)
            .where(Chunk.document_id == document_id, Document.tenant_id == tenant_id)
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
