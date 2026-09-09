import uuid
from datetime import UTC, datetime
from enum import Enum

from pgvector.sqlalchemy import Vector
from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.domain import Domain, document_domains

# Output size of OpenAI's text-embedding-3-small model.
# The database column must be exactly this many numbers wide.
EMBEDDING_DIMENSIONS = 1536


class DocumentStatus(str, Enum):
    """The stages a document moves through during ingestion.

    PENDING_REVIEW, IN_REVIEW, and REJECTED are the PII human-review
    workflow (ADR-048): a document with PII detected is held at
    PENDING_REVIEW until its uploader submits it, moves to IN_REVIEW for
    an admin of the same tenant to decide on, and ends at either READY
    (approved — reprocessed and embedded, the same as any other
    document) or REJECTED (terminal — no further review can be
    requested).
    """

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    PENDING_REVIEW = "pending_review"
    IN_REVIEW = "in_review"
    REJECTED = "rejected"


class ProcessingStage(str, Enum):
    """Which step of the pipeline a PROCESSING document is currently on.

    Only meaningful while status is PROCESSING — once a document reaches
    a terminal status (READY, FAILED, PENDING_REVIEW), the frontend stops
    polling and stops reading this field, so it's left wherever the
    pipeline last set it rather than reset to some "done" value.
    """

    QUEUED = "queued"
    EXTRACTING = "extracting"
    CHECKING_PII = "checking_pii"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    SAVING = "saving"


class Document(Base):
    """A single uploaded file and where it is in the ingestion pipeline."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[DocumentStatus] = mapped_column(
        SQLEnum(DocumentStatus), default=DocumentStatus.PENDING
    )
    processing_stage: Mapped[ProcessingStage] = mapped_column(
        SQLEnum(ProcessingStage), default=ProcessingStage.QUEUED
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    pii_detected: Mapped[bool] = mapped_column(default=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, default=None)
    # Real, admin-managed category tags ("HR", "Finance") — a many-to-many
    # link to the per-tenant Domain table, not free text (see app/models/domain.py).
    # A document can belong to more than one domain at once. Empty by
    # default: an untagged document simply never participates in domain
    # classification (see app/services/domain_classification.py) and stays
    # reachable only through the original, domain-agnostic search path.
    domain_objects: Mapped[list["Domain"]] = relationship(secondary=document_domains)
    # Where this document's original file lives in Blob Storage — just the
    # blob name (document id + extension), not a full URL, since the
    # container and account differ by environment (ADR-044). Null for any
    # document uploaded before this feature existed, or if the upload's
    # blob save itself failed — either way, nothing to view.
    storage_path: Mapped[str | None] = mapped_column(String(255), default=None)
    # Which tenant this document belongs to — set from the uploader's own
    # tenant at creation time, never changed afterward. This is the whole
    # access control mechanism now: any user in this tenant can see this
    # document, no per-document grant needed (ADR-046 replaced the old
    # per-user DocumentPermission table with this).
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    # Who uploaded this document — reintroduced (ADR-046 had removed all
    # per-user tracking on documents) specifically for the PII review
    # workflow (ADR-048): a document held for review is visible only to
    # its own uploader, not the whole tenant, until an admin decides on
    # it. Nullable because documents created before this feature existed
    # have no recorded uploader at all — treated as visible only to an
    # admin of the tenant, never to a specific "owner" that doesn't exist.
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id"), default=None
    )

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    @property
    def has_file(self) -> bool:
        """Whether this document's original file can actually be viewed."""
        return self.storage_path is not None

    @property
    def domains(self) -> list[str]:
        """Domain names this document is tagged with, for every read path
        (API responses, MCP, the audit log) that only ever needs the name.

        Kept as a same-named computed property (mirroring has_file above)
        specifically so DocumentListItem/DocumentUploadResponse's existing
        `model_validate(doc)` calls needed zero changes when the real
        column became this relationship. Requires domain_objects to
        already be loaded — eager-loaded wherever a Document is fetched
        for a response that reads this (see DocumentRepository).
        """
        return sorted(d.name for d in self.domain_objects)


class Chunk(Base):
    """One small piece of a document's text, plus its embedding vector."""

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    chunk_index: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))

    document: Mapped["Document"] = relationship(back_populates="chunks")


class DocumentUploadResponse(BaseModel):
    """What the API sends back to the client right after a file is uploaded."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    status: DocumentStatus
    domains: list[str]
    correlation_id: str


class DocumentListItem(BaseModel):
    """One document's summary, as shown in the document library."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    status: DocumentStatus
    uploaded_at: datetime
    pii_detected: bool
    domains: list[str]
    has_file: bool


class DocumentListResponse(BaseModel):
    """What the API sends back for a request to list a user's documents."""

    documents: list[DocumentListItem]
    correlation_id: str


class DocumentStatusResponse(BaseModel):
    """What the API sends back when the frontend polls a document's progress."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: DocumentStatus
    processing_stage: ProcessingStage
    pii_detected: bool
    failure_reason: str | None
    correlation_id: str
