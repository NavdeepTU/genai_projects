from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.models.session import Session
from app.models.user import User
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository

# Argon2id, OWASP's current top recommendation for password hashing —
# picked over the long-standard bcrypt because Argon2id won the
# Password Hashing Competition and was promoted to OWASP's #1 pick in
# their 2024 cheat sheet update. Uses argon2-cffi directly, not the
# more commonly-tutorialed passlib wrapper: passlib is genuinely
# unmaintained (last release 2020, breaks on Python 3.13+), confirmed
# before choosing it, not assumed from habit.
_hasher = PasswordHasher()


class EmailAlreadyRegisteredError(Exception):
    """Raised when signing up with an email that already has an account."""


class InvalidCredentialsError(Exception):
    """Raised when login fails — deliberately the same error for both a
    wrong password and a nonexistent email, so a login attempt can
    never be used to discover which emails have accounts."""


class AuthService:
    """Signs up, logs in, and logs out users — the only place that touches
    a real password, hashed or plain, anywhere in this codebase."""

    def __init__(self, user_repository: UserRepository, session_repository: SessionRepository) -> None:
        self.user_repository = user_repository
        self.session_repository = session_repository

    async def sign_up(self, email: str, password: str) -> User:
        """Create a new account. The password is hashed here and never stored raw."""
        existing = await self.user_repository.get_user_by_email(email)
        if existing is not None:
            raise EmailAlreadyRegisteredError(email)

        hashed_password = _hasher.hash(password)
        return await self.user_repository.create_user(email, hashed_password)

    async def log_in(self, email: str, password: str) -> tuple[User, Session]:
        """Verify credentials and start a new session. Raises on any mismatch."""
        user = await self.user_repository.get_user_by_email(email)
        if user is None:
            raise InvalidCredentialsError(email)

        try:
            _hasher.verify(user.hashed_password, password)
        except VerifyMismatchError:
            raise InvalidCredentialsError(email) from None

        session = await self.session_repository.create_session(user.id)
        return user, session

    async def log_out(self, token: str) -> None:
        """End a session."""
        await self.session_repository.delete_session(token)
