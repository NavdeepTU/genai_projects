from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_auth import require_admin
from app.core.database import get_db
from app.core.middleware import get_correlation_id
from app.models.admin import AdminAuditEntry, AdminResponse, DocumentPermissionEntry
from app.repositories.audit_repository import AuditRepository
from app.repositories.permission_repository import PermissionRepository

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("", response_model=AdminResponse)
async def get_admin(db: AsyncSession = Depends(get_db)) -> AdminResponse:
    """Return the admin digest: recent activity and document permissions, across every user."""
    correlation_id = get_correlation_id()

    audit_entries = await AuditRepository(db).get_all_recent_entries(correlation_id=correlation_id)
    permissions = await PermissionRepository(db).list_all_permissions()

    return AdminResponse(
        audit_entries=[
            AdminAuditEntry(
                timestamp=entry.timestamp,
                user_id=entry.user_id,
                action=entry.action,
                resource_type=entry.resource_type,
                resource_id=entry.resource_id,
            )
            for entry in audit_entries
        ],
        permissions=[
            DocumentPermissionEntry(
                document_id=document_id,
                filename=filename,
                user_id=user_id,
                granted_at=granted_at,
            )
            for document_id, filename, user_id, granted_at in permissions
        ],
        correlation_id=correlation_id,
    )
