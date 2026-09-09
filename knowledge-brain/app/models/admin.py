import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AdminAuditEntry(BaseModel):
    """One action taken by any user, for the admin audit log viewer."""

    timestamp: datetime
    tenant_id: str | None
    user_id: str | None
    action: str
    resource_type: str
    resource_id: str


class AdminResponse(BaseModel):
    """The admin panel's combined view — the audit log across every user and tenant.

    No more per-document permissions list (ADR-046 removed that whole
    mechanism) — document sharing is now just tenant membership, nothing
    left to enumerate per document.
    """

    audit_entries: list[AdminAuditEntry]
    correlation_id: str


class ReviewQueueItem(BaseModel):
    """One document awaiting a human PII-review decision (ADR-048)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    uploaded_at: datetime
    uploaded_by_email: str | None
    has_file: bool


class ReviewQueueResponse(BaseModel):
    """Every document currently IN_REVIEW in the admin's own tenant."""

    documents: list[ReviewQueueItem]
    correlation_id: str
