import uuid
from datetime import UTC, datetime
from enum import Enum

from pgvector.sqlalchemy import Vector
from pydantic import BaseModel, ConfigDict
from sqlalchemy import ARRAY, DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# Output size of OpenAI's text-embedding-3-small model.
# The database column must be exactly this many numbers wide.
EMBEDDING_DIMENSIONS = 1536


class DocumentStatus(str, Enum):
    """The stages a document moves through during ingestion."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    PENDING_REVIEW = "pending_review"


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
    # Free-text category tags, set manually at upload — "HR", "Finance", and
    # so on. A document can belong to more than one domain at once, hence a
    # plain array column here rather than a single string field. Empty by
    # default: an untagged document simply never participates in domain
    # classification (see app/services/domain_classification.py) and stays
    # reachable only through the original, domain-agnostic search path.
    domains: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


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
