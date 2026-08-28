import uuid
from datetime import datetime

from pydantic import BaseModel


class AdminAuditEntry(BaseModel):
    """One action taken by any user, for the admin audit log viewer."""

    timestamp: datetime
    user_id: str | None
    action: str
    resource_type: str
    resource_id: str


class DocumentPermissionEntry(BaseModel):
    """One document-permission grant, for the admin permissions viewer."""

    document_id: uuid.UUID
    filename: str
    user_id: str
    granted_at: datetime


class AdminResponse(BaseModel):
    """The admin panel's combined view — audit log and document permissions, across every user."""

    audit_entries: list[AdminAuditEntry]
    permissions: list[DocumentPermissionEntry]
    correlation_id: str
