import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.documents import (
    get_document_content,
    get_document_status,
    submit_document_for_review,
)
from app.core import middleware
from app.models.document import DocumentStatus
from app.repositories.audit_repository import AuditRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.tenant_repository import TenantRepository
from app.repositories.user_repository import UserRepository


async def _tenant_id(db_session, name: str = "Acme") -> uuid.UUID:
    tenant = await TenantRepository(db_session).create_tenant(name)
    return tenant.id


def _set_caller(tenant_id: uuid.UUID, user_id: uuid.UUID):
    return middleware._tenant_id.set(str(tenant_id)), middleware._user_id.set(str(user_id))


def _reset_caller(tokens) -> None:
    tenant_token, user_token = tokens
    middleware._tenant_id.reset(tenant_token)
    middleware._user_id.reset(user_token)


async def test_submit_document_for_review_succeeds_for_its_own_uploader(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    uploader = await UserRepository(db_session).create_user(
        "uploader@example.com", "hashed", tenant_id
    )

    document = await repository.create_document("flagged.txt", tenant_id, uploader.id)
    await repository.flag_for_review(document.id)

    tokens = _set_caller(tenant_id, uploader.id)
    try:
        response = await submit_document_for_review(document.id, db_session)
    finally:
        _reset_caller(tokens)

    assert response.status == DocumentStatus.IN_REVIEW
    audit = await AuditRepository(db_session).get_all_recent_entries()
    assert any(
        e.action == "document_submitted_for_review" and e.resource_id == str(document.id)
        for e in audit
    )


async def test_submit_document_for_review_404s_for_a_different_tenant_member(db_session):
    """Someone who isn't the uploader (and isn't an admin) gets the same 404
    shape as a document that doesn't exist — they shouldn't even learn it's there.
    """
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    uploader = await UserRepository(db_session).create_user(
        "uploader@example.com", "hashed", tenant_id
    )
    colleague = await UserRepository(db_session).create_user(
        "colleague@example.com", "hashed", tenant_id
    )

    document = await repository.create_document("flagged.txt", tenant_id, uploader.id)
    await repository.flag_for_review(document.id)

    tokens = _set_caller(tenant_id, colleague.id)
    try:
        with pytest.raises(HTTPException) as exc_info:
            await submit_document_for_review(document.id, db_session)
    finally:
        _reset_caller(tokens)

    assert exc_info.value.status_code == 404


async def test_submit_document_for_review_rejects_a_document_already_in_review(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    uploader = await UserRepository(db_session).create_user(
        "uploader@example.com", "hashed", tenant_id
    )

    document = await repository.create_document("flagged.txt", tenant_id, uploader.id)
    await repository.flag_for_review(document.id)
    await repository.submit_for_review(document.id)

    tokens = _set_caller(tenant_id, uploader.id)
    try:
        with pytest.raises(HTTPException) as exc_info:
            await submit_document_for_review(document.id, db_session)
    finally:
        _reset_caller(tokens)

    assert exc_info.value.status_code == 400


async def test_get_document_status_hides_a_held_document_from_a_non_uploader(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    uploader = await UserRepository(db_session).create_user(
        "uploader@example.com", "hashed", tenant_id
    )
    colleague = await UserRepository(db_session).create_user(
        "colleague@example.com", "hashed", tenant_id
    )

    document = await repository.create_document("flagged.txt", tenant_id, uploader.id)
    await repository.flag_for_review(document.id)

    tokens = _set_caller(tenant_id, colleague.id)
    try:
        with pytest.raises(HTTPException) as exc_info:
            await get_document_status(document.id, db_session)
    finally:
        _reset_caller(tokens)

    assert exc_info.value.status_code == 404


async def test_get_document_status_is_visible_to_an_admin_for_review(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    uploader = await UserRepository(db_session).create_user(
        "uploader@example.com", "hashed", tenant_id
    )
    admin = await UserRepository(db_session).create_user("admin@example.com", "hashed", tenant_id)
    admin.is_admin = True
    await db_session.commit()

    document = await repository.create_document("flagged.txt", tenant_id, uploader.id)
    await repository.flag_for_review(document.id)
    await repository.submit_for_review(document.id)

    tokens = _set_caller(tenant_id, admin.id)
    try:
        response = await get_document_status(document.id, db_session)
    finally:
        _reset_caller(tokens)

    assert response.status == DocumentStatus.IN_REVIEW


async def test_get_document_content_hides_a_held_document_from_a_non_uploader(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    uploader = await UserRepository(db_session).create_user(
        "uploader@example.com", "hashed", tenant_id
    )
    colleague = await UserRepository(db_session).create_user(
        "colleague@example.com", "hashed", tenant_id
    )

    document = await repository.create_document("flagged.txt", tenant_id, uploader.id)
    await repository.set_storage_path(document.id, f"{document.id}.txt")
    await repository.flag_for_review(document.id)

    tokens = _set_caller(tenant_id, colleague.id)
    try:
        with pytest.raises(HTTPException) as exc_info:
            await get_document_content(document.id, db_session)
    finally:
        _reset_caller(tokens)

    assert exc_info.value.status_code == 404


async def test_get_document_content_is_visible_to_its_own_uploader(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    uploader = await UserRepository(db_session).create_user(
        "uploader@example.com", "hashed", tenant_id
    )

    document = await repository.create_document("flagged.txt", tenant_id, uploader.id)
    await repository.set_storage_path(document.id, f"{document.id}.txt")
    await repository.flag_for_review(document.id)

    tokens = _set_caller(tenant_id, uploader.id)
    try:
        with patch(
            "app.api.documents.download_document",
            new=AsyncMock(return_value=b"the flagged content"),
        ):
            response = await get_document_content(document.id, db_session)
    finally:
        _reset_caller(tokens)

    assert response.body == b"the flagged content"
