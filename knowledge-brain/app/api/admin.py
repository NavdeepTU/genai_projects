from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_auth import require_admin
from app.core.database import get_db
from app.core.middleware import get_correlation_id, get_current_user_id
from app.models.admin import AdminAuditEntry, AdminResponse
from app.models.tenant import CreateTenantRequest, CreateTenantResponse
from app.repositories.audit_repository import AuditRepository
from app.repositories.tenant_repository import TenantRepository

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("", response_model=AdminResponse)
async def get_admin(db: AsyncSession = Depends(get_db)) -> AdminResponse:
    """Return the admin digest: recent activity across every user and tenant."""
    correlation_id = get_correlation_id()

    audit_entries = await AuditRepository(db).get_all_recent_entries(correlation_id=correlation_id)

    return AdminResponse(
        audit_entries=[
            AdminAuditEntry(
                timestamp=entry.timestamp,
                tenant_id=entry.tenant_id,
                user_id=entry.user_id,
                action=entry.action,
                resource_type=entry.resource_type,
                resource_id=entry.resource_id,
            )
            for entry in audit_entries
        ],
        correlation_id=correlation_id,
    )


@router.post("/tenants", response_model=CreateTenantResponse, status_code=201)
async def create_tenant(body: CreateTenantRequest, db: AsyncSession = Depends(get_db)) -> CreateTenantResponse:
    """Register a new tenant — the only way one can ever be created (ADR-046).

    A user never creates their own tenant; they only ever pick one that
    already exists (GET /tenants) at signup. Gated by require_admin at
    the router level, same as every other route here.
    """
    correlation_id = get_correlation_id()
    tenant_repository = TenantRepository(db)

    existing = await tenant_repository.get_tenant_by_name(body.name)
    if existing is not None:
        raise HTTPException(status_code=409, detail="A tenant with this name already exists")

    # The check above is only a friendlier common case — it can't stop two
    # concurrent requests for the same name from both passing it. The
    # unique constraint on tenants.name is the real guarantee; this catches
    # its violation and reports the same 409 rather than an unhandled 500.
    try:
        tenant = await tenant_repository.create_tenant(body.name)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="A tenant with this name already exists") from None

    await AuditRepository(db).log_action(
        correlation_id=correlation_id,
        action="tenant_registered",
        resource_type="tenant",
        resource_id=str(tenant.id),
        extra_data={"name": tenant.name},
        user_id=get_current_user_id(),
    )

    return CreateTenantResponse(id=tenant.id, name=tenant.name, correlation_id=correlation_id)
