import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Table, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Many-to-many: a document can carry more than one domain, a domain can tag
# more than one document. A plain association table, not a full ORM model —
# the link itself needs no identity or extra columns of its own.
# ondelete="CASCADE" on both sides means deleting a document or a domain
# cleans up its link rows automatically at the database level, regardless
# of which code path did the deleting.
document_domains = Table(
    "document_domains",
    Base.metadata,
    Column("document_id", ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
    Column("domain_id", ForeignKey("domains.id", ondelete="CASCADE"), primary_key=True),
)


class Domain(Base):
    """A real, admin-managed category tag ("HR", "Finance"), scoped to one tenant.

    Replaces the old free-text `Document.domains` array (ADR-040), which
    let "HR" and "Human Resources" exist as two unrelated tags with
    nothing to ever notice or fix that. A domain now exists exactly once
    per tenant — created, renamed, or merged by an admin only, never
    typed freely at upload — so vocabulary drift can't silently
    accumulate the way it used to.
    """

    __tablename__ = "domains"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


# A plain UniqueConstraint on (tenant_id, name) would be case-sensitive,
# letting "HR" and "hr" both insert for the same tenant even though
# get_by_name_for_tenant's pre-check is case-insensitive (ilike) — exactly
# the vocabulary-drift bug this taxonomy exists to prevent. Indexing
# lower(name) instead makes the database's own guarantee match the
# application's, so a race between two concurrent creates is still
# caught by the database, not just the pre-check.
Index(
    "uq_domain_tenant_name_ci",
    Domain.tenant_id,
    func.lower(Domain.name),
    unique=True,
)


class DomainResponse(BaseModel):
    """One domain, as shown in the admin panel or the upload form's picker."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class DomainDetailResponse(BaseModel):
    """What POST /admin/domains and PATCH /admin/domains/{id} send back for the single domain they just created or renamed."""

    id: uuid.UUID
    name: str
    correlation_id: str


class DomainListResponse(BaseModel):
    """What GET /domains sends back."""

    domains: list[DomainResponse]
    correlation_id: str


class CreateDomainRequest(BaseModel):
    """Body for POST /admin/domains."""

    name: str


class RenameDomainRequest(BaseModel):
    """Body for PATCH /admin/domains/{domain_id}."""

    name: str


class MergeDomainRequest(BaseModel):
    """Body for POST /admin/domains/{domain_id}/merge — merges this domain into target_id."""

    target_id: uuid.UUID
