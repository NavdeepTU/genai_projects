import logging
from datetime import UTC, datetime, timedelta

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

    async def log_query_made(
        self, *, correlation_id: str, user_id: str, question: str, duration_ms: float
    ) -> None:
        """Record one query_made action — the one shape both /query and MCP's ask_knowledge_base need.

        A named wrapper around log_action, not two hand-built extra_data
        dicts kept in sync by hand across two files — the exact drift
        this project already hit once, adding duration_ms to only one
        call site before this method existed.
        """
        await self.log_action(
            correlation_id=correlation_id,
            action="query_made",
            resource_type="query",
            resource_id=correlation_id,
            extra_data={"question": question, "duration_ms": duration_ms},
            user_id=user_id,
        )

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

    async def get_query_entries_for_user(
        self,
        user_id: str,
        days: int = 30,
        limit: int = 5000,
        correlation_id: str | None = None,
    ) -> list[AuditLog]:
        """Return this user's query_made entries from the last N days, newest first.

        Returns raw rows, not aggregates — grouping by day, counting
        repeated questions, and averaging duration all happen afterward
        in AnalyticsService, in Python, not as SQL aggregation over the
        extra_data JSONB column. At this project's scale that's simpler
        to read and change than JSONB path aggregation; a real rollup
        table would replace this if the row count ever made that cost
        actually matter.

        `limit` is a safety cap, not real pagination — at 5000 queries in
        30 days this silently drops the oldest entries in the window
        rather than growing memory unbounded; a genuinely high-volume
        user would need a real rollup, not a larger cap.

        correlation_id is accepted as a plain parameter, not read via
        get_correlation_id(), because that function lives in
        app.core.middleware, which itself imports AuditRepository —
        importing it back here would be a circular import. Same
        explicit-parameter reasoning ADR-030 already used for background
        tasks, applied here for a different reason (a real import cycle,
        not a stale contextvar).
        """
        since = datetime.now(UTC) - timedelta(days=days)
        stmt = (
            select(AuditLog)
            .where(
                AuditLog.action == "query_made",
                AuditLog.user_id == user_id,
                AuditLog.timestamp >= since,
            )
            .order_by(AuditLog.timestamp.desc())
            .limit(limit)
        )
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception(
                "Failed to fetch query analytics entries for user %s",
                user_id,
                extra={"correlation_id": correlation_id},
            )
            raise
        return list(result.scalars().all())

    async def get_all_recent_entries(
        self, limit: int = 50, correlation_id: str | None = None
    ) -> list[AuditLog]:
        """Return the most recent audit entries across every user and action type.

        Unscoped by user_id, unlike every other read method on this
        repository — genuinely admin-only, since it's the one query in
        this codebase that shows someone activity that isn't their own.
        Callers must gate this behind require_admin; this method itself
        does no authorization, only the query.
        """
        stmt = select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit)
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception(
                "Failed to fetch recent audit entries", extra={"correlation_id": correlation_id}
            )
            raise
        return list(result.scalars().all())
