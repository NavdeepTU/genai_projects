import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.middleware import get_correlation_id, get_current_user_id
from app.models.user import UserProfileResponse
from app.repositories.tenant_repository import TenantRepository
from app.repositories.user_repository import UserRepository

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserProfileResponse)
async def get_my_profile(db: AsyncSession = Depends(get_db)) -> UserProfileResponse:
    """Return the logged-in user's own read-only profile info.

    Separate from GET /auth/me on purpose (see UserProfileResponse's
    docstring) — this is the one place that resolves a tenant_id into its
    display name, so only the profile page pays for that join.
    """
    user = await UserRepository(db).get_user_by_id(uuid.UUID(get_current_user_id()))
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in")

    tenant = await TenantRepository(db).get_tenant_by_id(user.tenant_id)
    if tenant is None:
        raise HTTPException(status_code=500, detail="This account's tenant no longer exists")

    return UserProfileResponse(
        email=user.email,
        is_admin=user.is_admin,
        tenant_name=tenant.name,
        created_at=user.created_at,
        correlation_id=get_correlation_id(),
    )
