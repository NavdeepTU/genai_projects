import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


class AuditRepository:
    """Writes to the append-only audit log.

    Deliberately has no update or delete methods — the only thing you can
    do to the audit log is add to it.
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
