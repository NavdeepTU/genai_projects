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

# Output size of OpenAI's text-embedding-3-small model.
# The database column must be exactly this many numbers wide.
EMBEDDING_DIMENSIONS = 1536


class DocumentStatus(str, Enum):
    """The stages a document moves through during ingestion."""

    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Document(Base):
    """A single uploaded file and where it is in the ingestion pipeline."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[DocumentStatus] = mapped_column(
        SQLEnum(DocumentStatus), default=DocumentStatus.PENDING
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

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
    correlation_id: str
