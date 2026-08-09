import uuid
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DocumentPermission(Base):
    """One user's grant of access to one document — the whole ACL, one row per grant."""

    __tablename__ = "document_permissions"
    __table_args__ = (UniqueConstraint("document_id", "user_id", name="uq_document_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    user_id: Mapped[str] = mapped_column(String(64))
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class GrantAccessRequest(BaseModel):
    """Request body for sharing a document with another user."""

    user_id: str


class GrantAccessResponse(BaseModel):
    """What the API sends back after a document is successfully shared."""

    document_id: uuid.UUID
    granted_to: str
    correlation_id: str
