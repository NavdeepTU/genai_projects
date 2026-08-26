from app.repositories.audit_repository import AuditRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.permission_repository import PermissionRepository


async def test_count_documents_for_user_only_counts_accessible_documents(db_session):
    """A user's count should include only documents they've been granted access to."""
    repository = DocumentRepository(db_session)
    permissions = PermissionRepository(db_session)

    doc_a = await repository.create_document("a.txt")
    doc_b = await repository.create_document("b.txt")
    doc_c = await repository.create_document("c.txt")
    await permissions.grant_access(doc_a.id, "alice")
    await permissions.grant_access(doc_b.id, "alice")
    await permissions.grant_access(doc_c.id, "bob")

    assert await repository.count_documents_for_user("alice") == 2
    assert await repository.count_documents_for_user("bob") == 1
    assert await repository.count_documents_for_user("nobody") == 0


async def test_get_recent_queries_for_user_scoped_and_ordered(db_session):
    """Recent queries should only include this user's own, newest first, respecting limit."""
    audit = AuditRepository(db_session)

    await audit.log_action(
        correlation_id="c1",
        action="query_made",
        resource_type="query",
        resource_id="c1",
        extra_data={"question": "alice's first question"},
        user_id="alice",
    )
    await audit.log_action(
        correlation_id="c2",
        action="query_made",
        resource_type="query",
        resource_id="c2",
        extra_data={"question": "bob's question"},
        user_id="bob",
    )
    await audit.log_action(
        correlation_id="c3",
        action="query_made",
        resource_type="query",
        resource_id="c3",
        extra_data={"question": "alice's second question"},
        user_id="alice",
    )
    # Not a query — should never show up in "recent queries," even for alice.
    await audit.log_action(
        correlation_id="c4",
        action="document_upload",
        resource_type="document",
        resource_id="c4",
        extra_data={"filename": "notes.txt"},
        user_id="alice",
    )

    results = await audit.get_recent_queries_for_user("alice")

    assert [entry.extra_data["question"] for entry in results] == [
        "alice's second question",
        "alice's first question",
    ]


async def test_get_recent_queries_for_user_respects_limit(db_session):
    """The limit parameter should cap how many entries come back, newest first."""
    audit = AuditRepository(db_session)

    for i in range(3):
        await audit.log_action(
            correlation_id=f"c{i}",
            action="query_made",
            resource_type="query",
            resource_id=f"c{i}",
            extra_data={"question": f"question {i}"},
            user_id="alice",
        )

    results = await audit.get_recent_queries_for_user("alice", limit=2)

    assert len(results) == 2
    assert results[0].extra_data["question"] == "question 2"
