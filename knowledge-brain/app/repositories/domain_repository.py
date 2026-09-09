import logging
import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import Domain, document_domains

logger = logging.getLogger(__name__)


class DomainRepository:
    """All direct database access for the admin-managed domain taxonomy.

    Replaces the free-text `Document.domains` array this project started
    with (ADR-040) — a domain is now a real row, created/renamed/merged by
    an admin only, never typed freely at upload.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_domain(self, tenant_id: uuid.UUID, name: str) -> Domain:
        """Create a new domain for one tenant.

        Raises IntegrityError (via SQLAlchemyError) on a duplicate name —
        callers should check first with a case-insensitive lookup for a
        friendlier error, same pattern as tenant registration.
        """
        domain = Domain(tenant_id=tenant_id, name=name)
        self.session.add(domain)
        try:
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to create domain %r for tenant %s", name, tenant_id)
            raise
        await self.session.refresh(domain)
        return domain

    async def list_for_tenant(self, tenant_id: uuid.UUID) -> list[Domain]:
        """Every domain registered for a tenant, regardless of whether any
        document uses it yet — the picker an upload form or the admin
        panel actually shows, as opposed to DocumentRepository's own
        list_domains_for_tenant (only domains currently in use, the set
        the domain-classification supervisor chooses from)."""
        stmt = select(Domain).where(Domain.tenant_id == tenant_id).order_by(Domain.name)
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to list domains for tenant %s", tenant_id)
            raise
        return list(result.scalars().all())

    async def get_by_name_for_tenant(self, tenant_id: uuid.UUID, name: str) -> Domain | None:
        """Case-insensitive lookup, for a friendlier duplicate-name check before insert."""
        stmt = select(Domain).where(Domain.tenant_id == tenant_id, Domain.name.ilike(name))
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to look up domain %r for tenant %s", name, tenant_id)
            raise
        return result.scalar_one_or_none()

    async def get_by_id_for_tenant(self, domain_id: uuid.UUID, tenant_id: uuid.UUID) -> Domain | None:
        """Fetch one domain by id, scoped to the tenant it must belong to."""
        stmt = select(Domain).where(Domain.id == domain_id, Domain.tenant_id == tenant_id)
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to look up domain %s for tenant %s", domain_id, tenant_id)
            raise
        return result.scalar_one_or_none()

    async def rename_domain(self, domain_id: uuid.UUID, new_name: str) -> None:
        """Rename a domain — every document already tagged with it is unaffected
        (they still point at the same domain_id), so this single update is
        what actually fixes drift already noticed ("Human Resources" → "HR")."""
        stmt = update(Domain).where(Domain.id == domain_id).values(name=new_name)
        try:
            await self.session.execute(stmt)
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to rename domain %s", domain_id)
            raise

    async def merge_domain(self, source_id: uuid.UUID, target_id: uuid.UUID) -> None:
        """Reassign every document tagged with source to target instead, then delete source.

        A document already tagged with both ends up tagged with target
        only, not duplicated — the join table's composite primary key
        would reject inserting a (document_id, target_id) row that
        already exists, so the source link is dropped first for any
        document that already has the target too, before the bulk
        reassignment runs.
        """
        try:
            await self.session.execute(
                delete(document_domains).where(
                    document_domains.c.domain_id == source_id,
                    document_domains.c.document_id.in_(
                        select(document_domains.c.document_id).where(
                            document_domains.c.domain_id == target_id
                        )
                    ),
                )
            )
            await self.session.execute(
                update(document_domains)
                .where(document_domains.c.domain_id == source_id)
                .values(domain_id=target_id)
            )
            await self.session.execute(delete(Domain).where(Domain.id == source_id))
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to merge domain %s into %s", source_id, target_id)
            raise

    async def delete_domain(self, domain_id: uuid.UUID) -> None:
        """Delete a domain entirely — any document tagged with it is simply untagged,
        not deleted itself (ondelete=CASCADE on the join table only)."""
        try:
            await self.session.execute(delete(Domain).where(Domain.id == domain_id))
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to delete domain %s", domain_id)
            raise
