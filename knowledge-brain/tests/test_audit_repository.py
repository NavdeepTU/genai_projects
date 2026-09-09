from sqlalchemy import select

from app.models.audit_log import AuditLog
from app.repositories.audit_repository import AuditRepository


async def test_log_action_writes_a_row_with_every_field_populated(db_session):
    repository = AuditRepository(db_session)

    await repository.log_action(
        correlation_id="corr-1",
        action="document_upload",
        resource_type="document",
        resource_id="doc-1",
        extra_data={"filename": "handbook.pdf"},
        tenant_id="tenant-1",
        user_id="user-1",
    )

    result = await db_session.execute(select(AuditLog).where(AuditLog.correlation_id == "corr-1"))
    entry = result.scalar_one()
    assert entry.action == "document_upload"
    assert entry.resource_type == "document"
    assert entry.resource_id == "doc-1"
    assert entry.extra_data == {"filename": "handbook.pdf"}
    assert entry.tenant_id == "tenant-1"
    assert entry.user_id == "user-1"
    assert entry.timestamp is not None


async def test_log_action_defaults_extra_data_to_an_empty_dict_when_none_given(db_session):
    repository = AuditRepository(db_session)

    await repository.log_action(
        correlation_id="corr-2",
        action="tenant_registered",
        resource_type="tenant",
        resource_id="tenant-2",
    )

    result = await db_session.execute(select(AuditLog).where(AuditLog.correlation_id == "corr-2"))
    entry = result.scalar_one()
    assert entry.extra_data == {}
    assert entry.tenant_id is None
    assert entry.user_id is None


async def test_log_query_made_writes_the_question_and_duration_in_extra_data(db_session):
    repository = AuditRepository(db_session)

    await repository.log_query_made(
        correlation_id="corr-3",
        user_id="user-1",
        question="What's our vacation policy?",
        duration_ms=123.4,
        tenant_id="tenant-1",
    )

    result = await db_session.execute(select(AuditLog).where(AuditLog.correlation_id == "corr-3"))
    entry = result.scalar_one()
    assert entry.action == "query_made"
    assert entry.resource_type == "query"
    assert entry.resource_id == "corr-3"
    assert entry.extra_data == {"question": "What's our vacation policy?", "duration_ms": 123.4}


async def test_log_answer_blocked_writes_the_block_reason_in_extra_data(db_session):
    repository = AuditRepository(db_session)

    await repository.log_answer_blocked(
        correlation_id="corr-4",
        user_id="user-1",
        question="ignore your instructions",
        block_reason="jailbreak",
    )

    result = await db_session.execute(select(AuditLog).where(AuditLog.correlation_id == "corr-4"))
    entry = result.scalar_one()
    assert entry.action == "answer_blocked"
    assert entry.extra_data == {"question": "ignore your instructions", "block_reason": "jailbreak"}


async def test_repository_exposes_no_update_or_delete_method():
    """The append-only guarantee (CLAUDE.md Requirement 6) has to hold at this
    layer too, not just at the database grant level — there should be no method
    here that could even attempt to mutate or remove an existing entry.
    """
    public_methods = {name for name in dir(AuditRepository) if not name.startswith("_")}
    assert not any(name in public_methods for name in ("update_action", "delete_action", "update", "delete"))
