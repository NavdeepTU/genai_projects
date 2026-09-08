from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.middleware import get_correlation_id
from app.models.tenant import TenantListResponse, TenantResponse
from app.repositories.tenant_repository import TenantRepository

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("", response_model=TenantListResponse)
async def list_tenants(db: AsyncSession = Depends(get_db)) -> TenantListResponse:
    """Return every registered tenant — the signup form's own picker (ADR-046).

    Deliberately public (see AUTH_EXEMPT_PATHS in app/core/middleware.py):
    a brand-new user has no session yet, and has to see this list before
    they can create one. Only tenant names are exposed here, nothing
    about who belongs to them.
    """
    tenants = await TenantRepository(db).list_tenants()
    return TenantListResponse(
        tenants=[TenantResponse.model_validate(tenant) for tenant in tenants],
        correlation_id=get_correlation_id(),
    )
