import uuid

import pytest
from fastapi import HTTPException

from app.api.users import get_my_profile
from app.core import middleware
from app.repositories.tenant_repository import TenantRepository
from app.repositories.user_repository import UserRepository


def _set_caller(user_id: uuid.UUID):
    return middleware._user_id.set(str(user_id))


def _reset_caller(token) -> None:
    middleware._user_id.reset(token)


async def test_get_my_profile_returns_email_role_tenant_and_join_date(db_session):
    tenant = await TenantRepository(db_session).create_tenant("Acme")
    user = await UserRepository(db_session).create_user("uploader@example.com", "hashed", tenant.id)

    token = _set_caller(user.id)
    try:
        profile = await get_my_profile(db_session)
    finally:
        _reset_caller(token)

    assert profile.email == "uploader@example.com"
    assert profile.is_admin is False
    assert profile.tenant_name == "Acme"
    assert profile.created_at == user.created_at


async def test_get_my_profile_reflects_admin_status(db_session):
    tenant = await TenantRepository(db_session).create_tenant("Acme")
    admin = await UserRepository(db_session).create_user("admin@example.com", "hashed", tenant.id)
    admin.is_admin = True
    await db_session.commit()

    token = _set_caller(admin.id)
    try:
        profile = await get_my_profile(db_session)
    finally:
        _reset_caller(token)

    assert profile.is_admin is True


async def test_get_my_profile_401s_when_the_session_points_at_no_real_user(db_session):
    """A session_token that survived past its user being removed shouldn't
    surface as a crash — same 401 shape as any other "not really logged in" case."""
    token = _set_caller(uuid.uuid4())
    try:
        with pytest.raises(HTTPException) as exc_info:
            await get_my_profile(db_session)
    finally:
        _reset_caller(token)

    assert exc_info.value.status_code == 401
