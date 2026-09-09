import uuid

from app.models.document import DocumentStatus
from app.repositories.document_repository import DocumentRepository
from app.repositories.tenant_repository import TenantRepository
from app.repositories.user_repository import UserRepository


async def _tenant_id(db_session, name: str = "Acme") -> uuid.UUID:
    tenant = await TenantRepository(db_session).create_tenant(name)
    return tenant.id


async def _user_id(db_session, tenant_id: uuid.UUID, email: str = "uploader@example.com") -> uuid.UUID:
    user = await UserRepository(db_session).create_user(email, "hashed", tenant_id)
    return user.id


async def test_create_document_stores_domains(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    document = await repository.create_document("handbook.pdf", tenant_id, domains=["HR", "Finance"])

    assert document.domains == ["HR", "Finance"]


async def test_create_document_dedupes_repeated_domains(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    document = await repository.create_document(
        "handbook.pdf", tenant_id, domains=["HR", "HR", "Finance"]
    )

    assert document.domains == ["HR", "Finance"]


async def test_create_document_defaults_to_no_domains(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    document = await repository.create_document("misc.txt", tenant_id)

    assert document.domains == []


async def test_find_by_keyword_domain_filter_excludes_other_domains(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)

    hr_doc = await repository.create_document("hr.txt", tenant_id, domains=["HR"])
    finance_doc = await repository.create_document("finance.txt", tenant_id, domains=["Finance"])

    from app.models.document import Chunk

    embedding = [0.1] * 1536
    await repository.save_chunks(
        [
            Chunk(document_id=hr_doc.id, chunk_index=0, text="vacation policy details", embedding=embedding),
            Chunk(document_id=finance_doc.id, chunk_index=0, text="vacation budget details", embedding=embedding),
        ]
    )

    results = await repository.find_by_keyword("vacation", tenant_id, domain="HR")

    assert [c.document_id for c in results] == [hr_doc.id]


async def test_find_by_keyword_without_domain_searches_everything(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)

    hr_doc = await repository.create_document("hr.txt", tenant_id, domains=["HR"])
    finance_doc = await repository.create_document("finance.txt", tenant_id, domains=["Finance"])

    from app.models.document import Chunk

    embedding = [0.1] * 1536
    await repository.save_chunks(
        [
            Chunk(document_id=hr_doc.id, chunk_index=0, text="vacation policy details", embedding=embedding),
            Chunk(document_id=finance_doc.id, chunk_index=0, text="vacation budget details", embedding=embedding),
        ]
    )

    results = await repository.find_by_keyword("vacation", tenant_id)

    assert {c.document_id for c in results} == {hr_doc.id, finance_doc.id}


async def test_find_by_keyword_excludes_other_tenants_documents(db_session):
    """A tenant search must never surface another tenant's chunks (ADR-046)."""
    repository = DocumentRepository(db_session)
    tenant_a = await _tenant_id(db_session, "Acme")
    tenant_b = await _tenant_id(db_session, "Globex")

    doc_a = await repository.create_document("a.txt", tenant_a)
    doc_b = await repository.create_document("b.txt", tenant_b)

    from app.models.document import Chunk

    embedding = [0.1] * 1536
    await repository.save_chunks(
        [
            Chunk(document_id=doc_a.id, chunk_index=0, text="vacation policy details", embedding=embedding),
            Chunk(document_id=doc_b.id, chunk_index=0, text="vacation policy details", embedding=embedding),
        ]
    )

    results = await repository.find_by_keyword("vacation", tenant_a)

    assert [c.document_id for c in results] == [doc_a.id]


async def test_find_similar_chunks_domain_filter_excludes_other_domains(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)

    hr_doc = await repository.create_document("hr.txt", tenant_id, domains=["HR"])
    finance_doc = await repository.create_document("finance.txt", tenant_id, domains=["Finance"])

    from app.models.document import Chunk

    embedding = [0.1] * 1536
    await repository.save_chunks(
        [
            Chunk(document_id=hr_doc.id, chunk_index=0, text="hr chunk", embedding=embedding),
            Chunk(document_id=finance_doc.id, chunk_index=0, text="finance chunk", embedding=embedding),
        ]
    )

    results = await repository.find_similar_chunks(embedding, tenant_id, domain="HR")

    assert [c.document_id for c in results] == [hr_doc.id]


async def test_list_domains_for_tenant_returns_distinct_domains_across_documents(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    other_tenant_id = await _tenant_id(db_session, "Globex")

    await repository.create_document("a.txt", tenant_id, domains=["HR", "Onboarding"])
    await repository.create_document("b.txt", tenant_id, domains=["HR"])
    # A different tenant's document — its "Finance" domain must not appear.
    await repository.create_document("c.txt", other_tenant_id, domains=["Finance"])

    domains = await repository.list_domains_for_tenant(tenant_id)

    assert set(domains) == {"HR", "Onboarding"}


async def test_list_domains_for_tenant_ignores_untagged_documents(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)

    await repository.create_document("untagged.txt", tenant_id)

    domains = await repository.list_domains_for_tenant(tenant_id)

    assert domains == []


async def test_delete_document_cascades_chunks(db_session):
    """Deleting a document must remove its chunks too, not just the row —
    a leftover chunk pointing at a deleted document would be a real data-integrity gap.
    """
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)

    document = await repository.create_document("handbook.pdf", tenant_id)

    from sqlalchemy import select

    from app.models.document import Chunk

    await repository.save_chunks(
        [Chunk(document_id=document.id, chunk_index=0, text="a chunk", embedding=[0.1] * 1536)]
    )

    await repository.delete_document(document)

    assert await repository.get_by_id(document.id) is None

    remaining_chunks = await db_session.execute(
        select(Chunk).where(Chunk.document_id == document.id)
    )
    assert remaining_chunks.scalars().all() == []


async def test_get_document_for_tenant_hides_other_tenants_documents(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    other_tenant_id = await _tenant_id(db_session, "Globex")

    document = await repository.create_document("handbook.pdf", other_tenant_id)

    assert await repository.get_document_for_tenant(document.id, tenant_id) is None
    assert await repository.get_document_for_tenant(document.id, other_tenant_id) is not None


async def test_list_documents_for_tenant_hides_a_held_document_from_non_uploaders(db_session):
    """A PENDING_REVIEW/IN_REVIEW/REJECTED document is the one exception to
    tenant-wide visibility (ADR-048) — it only shows up for its own uploader.
    """
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    uploader_id = await _user_id(db_session, tenant_id, "uploader@example.com")
    other_user_id = await _user_id(db_session, tenant_id, "colleague@example.com")

    held = await repository.create_document("flagged.txt", tenant_id, uploader_id)
    await repository.flag_for_review(held.id)

    uploader_view = await repository.list_documents_for_tenant(tenant_id, uploader_id)
    other_view = await repository.list_documents_for_tenant(tenant_id, other_user_id)

    assert held.id in {doc.id for doc in uploader_view}
    assert held.id not in {doc.id for doc in other_view}


async def test_list_documents_for_tenant_shows_ready_documents_to_everyone(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    uploader_id = await _user_id(db_session, tenant_id, "uploader@example.com")
    other_user_id = await _user_id(db_session, tenant_id, "colleague@example.com")

    document = await repository.create_document("handbook.pdf", tenant_id, uploader_id)

    other_view = await repository.list_documents_for_tenant(tenant_id, other_user_id)

    assert document.id in {doc.id for doc in other_view}


async def test_submit_for_review_moves_pending_review_to_in_review(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    document = await repository.create_document("flagged.txt", tenant_id)
    await repository.flag_for_review(document.id)

    await repository.submit_for_review(document.id)

    refreshed = await repository.get_by_id(document.id)
    assert refreshed.status == DocumentStatus.IN_REVIEW


async def test_reject_document_is_terminal(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    document = await repository.create_document("flagged.txt", tenant_id)
    await repository.flag_for_review(document.id)
    await repository.submit_for_review(document.id)

    await repository.reject_document(document.id)

    refreshed = await repository.get_by_id(document.id)
    assert refreshed.status == DocumentStatus.REJECTED


async def test_list_review_queue_for_tenant_returns_only_in_review_documents_with_uploader_email(
    db_session,
):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    uploader_id = await _user_id(db_session, tenant_id, "uploader@example.com")

    held = await repository.create_document("flagged.txt", tenant_id, uploader_id)
    await repository.flag_for_review(held.id)
    await repository.submit_for_review(held.id)

    still_held = await repository.create_document("still-flagged.txt", tenant_id, uploader_id)
    await repository.flag_for_review(still_held.id)  # not yet submitted — shouldn't appear

    ready = await repository.create_document("normal.txt", tenant_id, uploader_id)

    queue = await repository.list_review_queue_for_tenant(tenant_id)

    queued_ids = {doc.id for doc, _email in queue}
    assert queued_ids == {held.id}
    assert next(email for doc, email in queue if doc.id == held.id) == "uploader@example.com"


async def test_list_review_queue_for_tenant_excludes_other_tenants(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    other_tenant_id = await _tenant_id(db_session, "Globex")

    document = await repository.create_document("flagged.txt", other_tenant_id)
    await repository.flag_for_review(document.id)
    await repository.submit_for_review(document.id)

    queue = await repository.list_review_queue_for_tenant(tenant_id)

    assert queue == []
