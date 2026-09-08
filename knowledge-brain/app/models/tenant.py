import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Tenant(Base):
    """A company/workspace — the grouping every user and document belongs to (ADR-046).

    Documents are shared within a tenant: any user in a tenant can see
    every document anyone in that tenant uploaded, with no per-document
    grant needed. A user picks their tenant once, at signup, from the
    list of tenants an admin has already registered — nobody can create
    a tenant for themselves.
    """

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class TenantResponse(BaseModel):
    """One tenant, as shown in the signup picker or the admin tenant list."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class TenantListResponse(BaseModel):
    """The full list of registered tenants — public, since it's needed before signup."""

    tenants: list[TenantResponse]
    correlation_id: str


class CreateTenantRequest(BaseModel):
    """Request body for an admin registering a new tenant."""

    name: str

    @field_validator("name")
    @classmethod
    def strip_and_require_nonempty(cls, value: str) -> str:
        """Trim whitespace before it ever reaches the duplicate-name check.

        Without this, " Acme" and "Acme" pass get_tenant_by_name as two
        distinct names, since the query matches on the raw string —
        silently defeating the one thing that check exists to prevent.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("Tenant name cannot be blank")
        return stripped


class CreateTenantResponse(BaseModel):
    """What the API sends back after a tenant is successfully registered."""

    id: uuid.UUID
    name: str
    correlation_id: str
