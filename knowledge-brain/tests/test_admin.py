import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.admin import create_tenant
from app.core import admin_auth, middleware
from app.models.tenant import CreateTenantRequest
from app.repositories.audit_repository import AuditRepository
from app.repositories.tenant_repository import TenantRepository
from app.repositories.user_repository import UserRepository


async def _tenant_id(db_session, name: str = "Acme") -> uuid.UUID:
    tenant = await TenantRepository(db_session).create_tenant(name)
    return tenant.id


async def test_require_admin_allows_a_real_admin_user(db_session):
    tenant_id = await _tenant_id(db_session)
    user = await UserRepository(db_session).create_user("admin@example.com", "hashed", tenant_id)
    user.is_admin = True
    await db_session.commit()

    token = middleware._user_id.set(str(user.id))
    try:
        await admin_auth.require_admin(db_session)  # should not raise
    finally:
        middleware._user_id.reset(token)


async def test_require_admin_rejects_a_non_admin_user(db_session):
    tenant_id = await _tenant_id(db_session)
    user = await UserRepository(db_session).create_user("regular@example.com", "hashed", tenant_id)

    token = middleware._user_id.set(str(user.id))
    try:
        with pytest.raises(HTTPException) as exc_info:
            await admin_auth.require_admin(db_session)
        assert exc_info.value.status_code == 403
    finally:
        middleware._user_id.reset(token)


async def test_require_admin_rejects_an_unknown_user_id(db_session):
    """A user id with no matching account (e.g. a stale or forged session) is rejected, not treated as non-admin-but-real."""
    token = middleware._user_id.set(str(uuid.uuid4()))
    try:
        with pytest.raises(HTTPException) as exc_info:
            await admin_auth.require_admin(db_session)
        assert exc_info.value.status_code == 403
    finally:
        middleware._user_id.reset(token)


async def test_get_all_recent_entries_spans_every_user_and_action(db_session):
    """Unlike get_recent_queries_for_user, this shouldn't filter by user_id or action."""
    audit = AuditRepository(db_session)

    await audit.log_action(
        correlation_id="c1",
        action="document_upload",
        resource_type="document",
        resource_id="c1",
        user_id="alice",
    )
    await audit.log_query_made(
        correlation_id="c2", user_id="bob", question="a question", duration_ms=100.0
    )

    entries = await audit.get_all_recent_entries()

    user_actions = {(e.user_id, e.action) for e in entries}
    assert ("alice", "document_upload") in user_actions
    assert ("bob", "query_made") in user_actions


async def test_create_tenant_converts_a_concurrent_duplicate_into_409(db_session):
    """The pre-check (get_tenant_by_name) can't stop two concurrent requests for the
    same name from both seeing 'no duplicate' and both proceeding — only the unique
    constraint on tenants.name actually prevents the second row. Simulated here by
    forcing the pre-check to report no duplicate even though one already exists,
    so the real conflict is only discovered at commit time (an IntegrityError),
    which the route must convert into the same 409, not an unhandled 500.
    """
    await TenantRepository(db_session).create_tenant("Acme")

    with patch(
        "app.repositories.tenant_repository.TenantRepository.get_tenant_by_name",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await create_tenant(CreateTenantRequest(name="Acme"), db_session)

    assert exc_info.value.status_code == 409
