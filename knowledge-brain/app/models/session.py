import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

SESSION_LIFETIME = timedelta(days=7)


def _default_expiry() -> datetime:
    return datetime.now(UTC) + SESSION_LIFETIME


class Session(Base):
    """One logged-in browser session — the server-side half of the session cookie.

    `token` is the actual secret sent to the browser as a cookie value,
    a long random string, not this row's own `id` — so a session id
    ever appearing in a log line (as `id`s routinely do throughout this
    project) can't be used to forge a login the way leaking the real
    token would.
    """

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_default_expiry)
