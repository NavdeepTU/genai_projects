import logging
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_permission import DocumentPermission

logger = logging.getLogger(__name__)


class PermissionRepository:
    """All direct database access for document permissions lives here."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def grant_access(self, document_id: uuid.UUID, user_id: str) -> None:
        """Give one user access to one document. Safe to call more than once.

        Uses ON CONFLICT DO NOTHING rather than checking first, so two
        concurrent grants for the same document/user can't race each
        other into a duplicate-row error.
        """
        stmt = (
            insert(DocumentPermission)
            .values(document_id=document_id, user_id=user_id)
            .on_conflict_do_nothing(index_elements=["document_id", "user_id"])
        )
        try:
            await self.session.execute(stmt)
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to grant access to document %s for user %s", document_id, user_id)
            raise

    async def has_access(self, document_id: uuid.UUID, user_id: str) -> bool:
        """Return whether this user has been granted access to this document."""
        stmt = select(DocumentPermission.id).where(
            DocumentPermission.document_id == document_id,
            DocumentPermission.user_id == user_id,
        )
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to check access for document %s, user %s", document_id, user_id)
            raise
        return result.scalar_one_or_none() is not None
