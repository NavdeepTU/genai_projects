import uuid

import pytest
from fastapi import HTTPException

from app.core import admin_auth, middleware
from app.repositories.audit_repository import AuditRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.permission_repository import PermissionRepository
from app.repositories.user_repository import UserRepository


async def test_require_admin_allows_a_real_admin_user(db_session):
    user = await UserRepository(db_session).create_user("admin@example.com", "hashed")
    user.is_admin = True
    await db_session.commit()

    token = middleware._user_id.set(str(user.id))
    try:
        await admin_auth.require_admin(db_session)  # should not raise
    finally:
        middleware._user_id.reset(token)


async def test_require_admin_rejects_a_non_admin_user(db_session):
    user = await UserRepository(db_session).create_user("regular@example.com", "hashed")

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


async def test_list_all_permissions_spans_every_user_and_document(db_session):
    """Unlike has_access, this should return grants for every user, not just one."""
    documents = DocumentRepository(db_session)
    permissions = PermissionRepository(db_session)

    doc_a = await documents.create_document("a.txt")
    doc_b = await documents.create_document("b.txt")
    await permissions.grant_access(doc_a.id, "alice")
    await permissions.grant_access(doc_b.id, "bob")

    all_permissions = await permissions.list_all_permissions()

    granted_pairs = {(row.filename, row.user_id) for row in all_permissions}
    assert ("a.txt", "alice") in granted_pairs
    assert ("b.txt", "bob") in granted_pairs


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
