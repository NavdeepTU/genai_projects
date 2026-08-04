import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditLog(Base):
    """An append-only record of every state-changing action taken in the system.

    Insert-only by convention at the code level (see AuditRepository, which
    has no update or delete methods). True database-level enforcement needs
    a restricted DB role, which we don't have set up locally yet.
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    correlation_id: Mapped[str] = mapped_column(String(64))
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(64))
    extra_data: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
