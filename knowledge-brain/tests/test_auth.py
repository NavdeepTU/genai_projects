import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.session import Session
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService, EmailAlreadyRegisteredError, InvalidCredentialsError


async def test_sign_up_creates_a_user_with_a_hashed_password(db_session):
    service = AuthService(UserRepository(db_session), SessionRepository(db_session))

    user = await service.sign_up("alice@example.com", "correct horse battery staple")

    assert user.email == "alice@example.com"
    assert user.hashed_password != "correct horse battery staple"


async def test_sign_up_rejects_a_duplicate_email(db_session):
    service = AuthService(UserRepository(db_session), SessionRepository(db_session))
    await service.sign_up("alice@example.com", "first-password")

    with pytest.raises(EmailAlreadyRegisteredError):
        await service.sign_up("alice@example.com", "second-password")


async def test_log_in_succeeds_with_the_right_password_and_starts_a_session(db_session):
    service = AuthService(UserRepository(db_session), SessionRepository(db_session))
    await service.sign_up("alice@example.com", "correct horse battery staple")

    user, session = await service.log_in("alice@example.com", "correct horse battery staple")

    assert user.email == "alice@example.com"
    assert session.user_id == user.id
    assert session.token


async def test_log_in_rejects_a_wrong_password(db_session):
    service = AuthService(UserRepository(db_session), SessionRepository(db_session))
    await service.sign_up("alice@example.com", "correct horse battery staple")

    with pytest.raises(InvalidCredentialsError):
        await service.log_in("alice@example.com", "wrong-password")


async def test_log_in_rejects_an_unknown_email(db_session):
    """Same error as a wrong password — a login attempt should never reveal which emails exist."""
    service = AuthService(UserRepository(db_session), SessionRepository(db_session))

    with pytest.raises(InvalidCredentialsError):
        await service.log_in("nobody@example.com", "whatever")


async def test_log_out_deletes_the_session(db_session):
    service = AuthService(UserRepository(db_session), SessionRepository(db_session))
    await service.sign_up("alice@example.com", "correct horse battery staple")
    _, session = await service.log_in("alice@example.com", "correct horse battery staple")

    await service.log_out(session.token)

    assert await SessionRepository(db_session).get_user_by_token(session.token) is None


async def test_log_out_on_an_already_invalid_token_does_not_raise(db_session):
    service = AuthService(UserRepository(db_session), SessionRepository(db_session))
    await service.log_out("this-token-was-never-real")


async def test_get_user_by_token_returns_none_for_an_expired_session(db_session):
    user_repository = UserRepository(db_session)
    session_repository = SessionRepository(db_session)
    user = await user_repository.create_user("alice@example.com", "hashed")

    expired = Session(token="expired-token", user_id=user.id, expires_at=datetime.now(UTC) - timedelta(days=1))
    db_session.add(expired)
    await db_session.commit()

    assert await session_repository.get_user_by_token("expired-token") is None


async def test_get_user_by_id_returns_none_for_an_unknown_id(db_session):
    user_repository = UserRepository(db_session)

    assert await user_repository.get_user_by_id(uuid.uuid4()) is None
