import logging

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


class AuditRepository:
    """Writes to, and reads from, the append-only audit log.

    Deliberately has no update or delete methods — the only things you
    can do to the audit log are add to it and read from it.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def log_action(
        self,
        *,
        correlation_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        extra_data: dict | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        """Record one state-changing action."""
        entry = AuditLog(
            correlation_id=correlation_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            extra_data=extra_data or {},
            tenant_id=tenant_id,
            user_id=user_id,
        )
        self.session.add(entry)
        try:
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to write audit log entry for action %s", action)
            raise

    async def get_recent_queries_for_user(self, user_id: str, limit: int = 5) -> list[AuditLog]:
        """Return this user's most recent query_made entries, newest first.

        Scoped to user_id in the query itself, not filtered afterward —
        the audit log holds every user's activity, and there's no reason
        one person's dashboard should ever pull rows belonging to
        someone else's questions across the network to filter client-side.
        """
        stmt = (
            select(AuditLog)
            .where(AuditLog.action == "query_made", AuditLog.user_id == user_id)
            .order_by(AuditLog.timestamp.desc())
            .limit(limit)
        )
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to fetch recent queries for user %s", user_id)
            raise
        return list(result.scalars().all())
