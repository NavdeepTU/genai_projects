import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.middleware import get_correlation_id, get_current_tenant_id
from app.models.domain import DomainListResponse, DomainResponse
from app.repositories.domain_repository import DomainRepository

router = APIRouter(prefix="/domains", tags=["domains"])


@router.get("", response_model=DomainListResponse)
async def list_domains(db: AsyncSession = Depends(get_db)) -> DomainListResponse:
    """Return every domain registered for the caller's own tenant.

    Available to any signed-in tenant member, not admin-only — this is
    what populates the upload form's domain picker, and creating a
    document needs no admin privilege of its own. Only creating,
    renaming, merging, or deleting a domain is admin-gated (see
    app/api/admin.py); picking from the list is not.
    """
    tenant_id = uuid.UUID(get_current_tenant_id())
    domains = await DomainRepository(db).list_for_tenant(tenant_id)

    return DomainListResponse(
        domains=[DomainResponse.model_validate(d) for d in domains],
        correlation_id=get_correlation_id(),
    )
