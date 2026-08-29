import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

logger = logging.getLogger(__name__)


class UserRepository:
    """All direct database access for user accounts."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_user(self, email: str, hashed_password: str) -> User:
        """Insert a new user account. Raises if the email is already taken.

        Relies on the unique index on User.email to reject a duplicate
        at the database level — the caller (AuthService) checks first
        for a friendly error message, but this is the real guarantee
        against a race between two concurrent signups for the same email.
        """
        user = User(email=email, hashed_password=hashed_password)
        self.session.add(user)
        try:
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to create user account for %s", email)
            raise
        await self.session.refresh(user)
        return user

    async def get_user_by_email(self, email: str) -> User | None:
        """Return the user with this email, if one exists."""
        stmt = select(User).where(User.email == email)
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to look up user by email")
            raise
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        """Return the user with this id, if one exists."""
        return await self.session.get(User, user_id)
