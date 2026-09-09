import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.admin import approve_document, create_tenant, get_review_queue, reject_document
from app.core import admin_auth, middleware
from app.models.document import DocumentStatus
from app.models.tenant import CreateTenantRequest
from app.repositories.audit_repository import AuditRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.tenant_repository import TenantRepository
from app.repositories.user_repository import UserRepository


async def _tenant_id(db_session, name: str = "Acme") -> uuid.UUID:
    tenant = await TenantRepository(db_session).create_tenant(name)
    return tenant.id


def _set_caller(tenant_id: uuid.UUID, user_id: uuid.UUID):
    """Set both context vars a real request's middleware would have set, returning reset tokens."""
    return middleware._tenant_id.set(str(tenant_id)), middleware._user_id.set(str(user_id))


def _reset_caller(tokens) -> None:
    tenant_token, user_token = tokens
    middleware._tenant_id.reset(tenant_token)
    middleware._user_id.reset(user_token)


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


async def test_approve_document_starts_reprocessing_and_logs_audit(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    admin = await UserRepository(db_session).create_user("admin@example.com", "hashed", tenant_id)

    document = await repository.create_document("flagged.txt", tenant_id)
    await repository.flag_for_review(document.id)
    await repository.submit_for_review(document.id)

    tokens = _set_caller(tenant_id, admin.id)
    try:
        response = await approve_document(document.id, BackgroundTasks(), db_session)
    finally:
        _reset_caller(tokens)

    assert response.status == DocumentStatus.PROCESSING

    audit = await AuditRepository(db_session).get_all_recent_entries()
    assert any(e.action == "document_approved" and e.resource_id == str(document.id) for e in audit)


async def test_approve_document_rejects_a_document_not_awaiting_review(db_session):
    """A document still PENDING_REVIEW (never submitted) can't be approved directly —
    it has to go through submit-review first.
    """
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    admin = await UserRepository(db_session).create_user("admin@example.com", "hashed", tenant_id)

    document = await repository.create_document("flagged.txt", tenant_id)
    await repository.flag_for_review(document.id)

    tokens = _set_caller(tenant_id, admin.id)
    try:
        with pytest.raises(HTTPException) as exc_info:
            await approve_document(document.id, BackgroundTasks(), db_session)
    finally:
        _reset_caller(tokens)

    assert exc_info.value.status_code == 400


async def test_approve_document_404s_for_a_document_in_another_tenant(db_session):
    """An admin can only approve their own tenant's flagged documents (ADR-048) —
    the exact cross-tenant boundary ADR-046 established everywhere else.
    """
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    other_tenant_id = await _tenant_id(db_session, "Globex")
    admin = await UserRepository(db_session).create_user("admin@example.com", "hashed", tenant_id)

    document = await repository.create_document("flagged.txt", other_tenant_id)
    await repository.flag_for_review(document.id)
    await repository.submit_for_review(document.id)

    tokens = _set_caller(tenant_id, admin.id)
    try:
        with pytest.raises(HTTPException) as exc_info:
            await approve_document(document.id, BackgroundTasks(), db_session)
    finally:
        _reset_caller(tokens)

    assert exc_info.value.status_code == 404


async def test_reject_document_moves_to_terminal_rejected_and_logs_audit(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    admin = await UserRepository(db_session).create_user("admin@example.com", "hashed", tenant_id)

    document = await repository.create_document("flagged.txt", tenant_id)
    await repository.flag_for_review(document.id)
    await repository.submit_for_review(document.id)

    tokens = _set_caller(tenant_id, admin.id)
    try:
        response = await reject_document(document.id, db_session)
    finally:
        _reset_caller(tokens)

    assert response.status == DocumentStatus.REJECTED
    refreshed = await repository.get_by_id(document.id)
    assert refreshed.status == DocumentStatus.REJECTED

    audit = await AuditRepository(db_session).get_all_recent_entries()
    assert any(e.action == "document_rejected" and e.resource_id == str(document.id) for e in audit)


async def test_get_review_queue_returns_only_this_tenants_in_review_documents(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    other_tenant_id = await _tenant_id(db_session, "Globex")
    admin = await UserRepository(db_session).create_user("admin@example.com", "hashed", tenant_id)
    uploader = await UserRepository(db_session).create_user(
        "uploader@example.com", "hashed", tenant_id
    )

    mine = await repository.create_document("flagged.txt", tenant_id, uploader.id)
    await repository.flag_for_review(mine.id)
    await repository.submit_for_review(mine.id)

    other = await repository.create_document("other-flagged.txt", other_tenant_id)
    await repository.flag_for_review(other.id)
    await repository.submit_for_review(other.id)

    tokens = _set_caller(tenant_id, admin.id)
    try:
        response = await get_review_queue(db_session)
    finally:
        _reset_caller(tokens)

    ids = {item.id for item in response.documents}
    assert ids == {mine.id}
    assert next(item for item in response.documents if item.id == mine.id).uploaded_by_email == (
        "uploader@example.com"
    )
