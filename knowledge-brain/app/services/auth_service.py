import uuid

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.redis_cache import invalidate_identity
from app.models.session import Session
from app.models.user import User
from app.repositories.session_repository import SessionRepository
from app.repositories.tenant_repository import TenantRepository
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


class TenantNotFoundError(Exception):
    """Raised when signing up with a tenant_id that isn't a real, registered tenant."""


class InvalidCredentialsError(Exception):
    """Raised when login fails — deliberately the same error for both a
    wrong password and a nonexistent email, so a login attempt can
    never be used to discover which emails have accounts."""


class AuthService:
    """Signs up, logs in, and logs out users — the only place that touches
    a real password, hashed or plain, anywhere in this codebase."""

    def __init__(
        self,
        user_repository: UserRepository,
        session_repository: SessionRepository,
        tenant_repository: TenantRepository,
    ) -> None:
        self.user_repository = user_repository
        self.session_repository = session_repository
        self.tenant_repository = tenant_repository

    async def sign_up(self, email: str, password: str, tenant_id: uuid.UUID) -> User:
        """Create a new account in an already-registered tenant (ADR-046).

        The password is hashed here and never stored raw. tenant_id must
        belong to a real, admin-registered tenant — a made-up or stale
        id (the client can send any UUID it wants) is rejected rather
        than silently creating a user with a dangling tenant reference.
        """
        existing = await self.user_repository.get_user_by_email(email)
        if existing is not None:
            raise EmailAlreadyRegisteredError(email)

        tenant = await self.tenant_repository.get_tenant_by_id(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(tenant_id)

        hashed_password = _hasher.hash(password)
        return await self.user_repository.create_user(email, hashed_password, tenant_id)

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
        """End a session, and clear its cached identity so the middleware's
        60-second cache (app/core/redis_cache.py) can't keep treating a
        just-revoked session as valid until that cache entry expires on its own."""
        await self.session_repository.delete_session(token)
        await invalidate_identity(token)
