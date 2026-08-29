import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, EmailStr
from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class User(Base):
    """A real, authenticated account — replaces the self-asserted X-User-Id header.

    hashed_password never holds the actual password, only the one-way
    Argon2id hash of it (see app/services/auth_service.py) — even a full
    database leak never exposes a real password.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class SignupRequest(BaseModel):
    """Request body for creating a new account."""

    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    """Request body for logging into an existing account."""

    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """A user's own account info, returned after signup/login and from /auth/me."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    is_admin: bool
    correlation_id: str
