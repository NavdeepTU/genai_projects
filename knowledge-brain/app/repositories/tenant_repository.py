import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant import Tenant

logger = logging.getLogger(__name__)


class TenantRepository:
    """All direct database access for tenants lives here."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_tenant(self, name: str) -> Tenant:
        """Register a new tenant. Raises if the name is already taken.

        Relies on the unique index on Tenant.name for the real guarantee
        against a race between two concurrent registrations of the same
        name — the caller checks first only for a friendlier error.
        """
        tenant = Tenant(name=name)
        self.session.add(tenant)
        try:
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to create tenant %s", name)
            raise
        await self.session.refresh(tenant)
        return tenant

    async def list_tenants(self) -> list[Tenant]:
        """Return every registered tenant, oldest first — the signup picker's own list."""
        stmt = select(Tenant).order_by(Tenant.created_at.asc())
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to list tenants")
            raise
        return list(result.scalars().all())

    async def get_tenant_by_id(self, tenant_id: uuid.UUID) -> Tenant | None:
        """Return the tenant with this id, if one exists — used to validate a signup choice."""
        return await self.session.get(Tenant, tenant_id)

    async def get_tenant_by_name(self, name: str) -> Tenant | None:
        """Return the tenant with this name, if one exists — for a friendly duplicate-name error."""
        stmt = select(Tenant).where(Tenant.name == name)
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to look up tenant by name")
            raise
        return result.scalar_one_or_none()
