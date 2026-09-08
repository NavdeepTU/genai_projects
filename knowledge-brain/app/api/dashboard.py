import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.middleware import get_correlation_id, get_current_tenant_id, get_current_user_id
from app.models.dashboard import DashboardResponse, RecentQuery
from app.repositories.audit_repository import AuditRepository
from app.repositories.document_repository import DocumentRepository

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
async def get_dashboard(db: AsyncSession = Depends(get_db)) -> DashboardResponse:
    """Return a summary digest for this user.

    document_count is tenant-wide (ADR-046) — every document the user's
    tenant can see, not just ones they personally uploaded, matching how
    the Document Library page itself now shows the whole tenant's
    documents. recent_queries stays personal: a user's own question
    history isn't shared just because their documents are.
    """
    user_id = get_current_user_id()
    tenant_id = uuid.UUID(get_current_tenant_id())

    document_count = await DocumentRepository(db).count_documents_for_tenant(tenant_id)
    recent_entries = await AuditRepository(db).get_recent_queries_for_user(user_id)

    return DashboardResponse(
        document_count=document_count,
        recent_queries=[
            RecentQuery(question=entry.extra_data["question"], asked_at=entry.timestamp)
            for entry in recent_entries
        ],
        correlation_id=get_correlation_id(),
    )
