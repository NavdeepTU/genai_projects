import logging
import uuid
from datetime import datetime

from sqlalchemy import Row, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
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

    async def list_all_permissions(self) -> list[Row[tuple[uuid.UUID, str, str, datetime]]]:
        """Return every document-permission grant across every document and user.

        Unscoped, unlike has_access/grant_access — genuinely admin-only,
        the permission-side equivalent of AuditRepository's
        get_all_recent_entries. Joined against Document for the filename,
        since a raw document_id is useless to a human reading this list.
        """
        stmt = (
            select(
                DocumentPermission.document_id,
                Document.filename,
                DocumentPermission.user_id,
                DocumentPermission.granted_at,
            )
            .join(Document, Document.id == DocumentPermission.document_id)
            .order_by(DocumentPermission.granted_at.desc())
        )
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to list all document permissions")
            raise
        return list(result.all())
