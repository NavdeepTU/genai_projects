import logging
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.models.user import User

logger = logging.getLogger(__name__)


class SessionRepository:
    """All direct database access for logged-in sessions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_session(self, user_id: uuid.UUID) -> Session:
        """Start a new session for a user, generating a fresh, random token.

        secrets.token_urlsafe (not uuid4, not a counter) specifically —
        this token is the actual credential a stolen cookie would hand
        an attacker, so it needs to be unguessable, not just unique.
        """
        db_session = Session(token=secrets.token_urlsafe(32), user_id=user_id)
        self.session.add(db_session)
        try:
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to create session for user %s", user_id)
            raise
        await self.session.refresh(db_session)
        return db_session

    async def get_user_by_token(self, token: str) -> User | None:
        """Return the user this session token belongs to, if it's real and unexpired.

        A missing token and an expired token both simply return None —
        the caller (the auth middleware) treats "no valid session" as
        one case, not two, the same way an invalid password and a
        nonexistent email both just mean "login failed."
        """
        stmt = (
            select(User)
            .join(Session, Session.user_id == User.id)
            .where(Session.token == token, Session.expires_at > datetime.now(UTC))
        )
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to validate session token")
            raise
        return result.scalar_one_or_none()

    async def delete_session(self, token: str) -> None:
        """End a session — logout. Safe to call on an already-invalid token."""
        stmt = delete(Session).where(Session.token == token)
        try:
            await self.session.execute(stmt)
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to delete session")
            raise
