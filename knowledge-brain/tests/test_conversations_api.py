import pytest
from fastapi import HTTPException

from app.api.conversations import delete_conversation
from app.core import middleware
from app.repositories.audit_repository import AuditRepository
from app.repositories.conversation_repository import ConversationRepository


def _set_caller(tenant_id: str, user_id: str):
    return middleware._tenant_id.set(tenant_id), middleware._user_id.set(user_id)


def _reset_caller(tokens) -> None:
    tenant_token, user_token = tokens
    middleware._tenant_id.reset(tenant_token)
    middleware._user_id.reset(user_token)


async def test_delete_conversation_removes_it_and_writes_an_audit_entry(db_session):
    repository = ConversationRepository(db_session)
    conversation = await repository.create_conversation("user-1", "Vacation policy")
    await repository.add_turn(
        conversation.id,
        raw_question="q",
        condensed_question="q",
        answer="a",
        sources=[],
        confidence=None,
        domains_used=[],
        correlation_id="corr-1",
    )

    tokens = _set_caller("tenant-1", "user-1")
    try:
        await delete_conversation(conversation.id, db_session)
    finally:
        _reset_caller(tokens)

    assert await repository.get_conversation_for_user(conversation.id, "user-1") is None
    audit = await AuditRepository(db_session).get_all_recent_entries()
    assert any(
        e.action == "conversation_deleted"
        and e.resource_type == "conversation"
        and e.resource_id == str(conversation.id)
        and e.tenant_id == "tenant-1"
        and e.user_id == "user-1"
        for e in audit
    )


async def test_delete_conversation_404s_for_a_different_user(db_session):
    """Someone who didn't start the conversation gets the same 404 shape as one
    that doesn't exist — same reasoning as get_conversation_for_user (ADR-046)."""
    repository = ConversationRepository(db_session)
    conversation = await repository.create_conversation("user-1", "Private thread")

    tokens = _set_caller("tenant-1", "user-2")
    try:
        with pytest.raises(HTTPException) as exc_info:
            await delete_conversation(conversation.id, db_session)
    finally:
        _reset_caller(tokens)

    assert exc_info.value.status_code == 404
    assert await repository.get_conversation_for_user(conversation.id, "user-1") is not None
