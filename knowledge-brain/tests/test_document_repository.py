from app.repositories.document_repository import DocumentRepository
from app.repositories.permission_repository import PermissionRepository


async def test_create_document_stores_domains(db_session):
    repository = DocumentRepository(db_session)
    document = await repository.create_document("handbook.pdf", domains=["HR", "Finance"])

    assert document.domains == ["HR", "Finance"]


async def test_create_document_dedupes_repeated_domains(db_session):
    repository = DocumentRepository(db_session)
    document = await repository.create_document("handbook.pdf", domains=["HR", "HR", "Finance"])

    assert document.domains == ["HR", "Finance"]


async def test_create_document_defaults_to_no_domains(db_session):
    repository = DocumentRepository(db_session)
    document = await repository.create_document("misc.txt")

    assert document.domains == []


async def test_find_by_keyword_domain_filter_excludes_other_domains(db_session):
    repository = DocumentRepository(db_session)
    permissions = PermissionRepository(db_session)

    hr_doc = await repository.create_document("hr.txt", domains=["HR"])
    finance_doc = await repository.create_document("finance.txt", domains=["Finance"])
    await permissions.grant_access(hr_doc.id, "user-1")
    await permissions.grant_access(finance_doc.id, "user-1")

    from app.models.document import Chunk

    embedding = [0.1] * 1536
    await repository.save_chunks(
        [
            Chunk(document_id=hr_doc.id, chunk_index=0, text="vacation policy details", embedding=embedding),
            Chunk(document_id=finance_doc.id, chunk_index=0, text="vacation budget details", embedding=embedding),
        ]
    )

    results = await repository.find_by_keyword("vacation", "user-1", domain="HR")

    assert [c.document_id for c in results] == [hr_doc.id]


async def test_find_by_keyword_without_domain_searches_everything(db_session):
    repository = DocumentRepository(db_session)
    permissions = PermissionRepository(db_session)

    hr_doc = await repository.create_document("hr.txt", domains=["HR"])
    finance_doc = await repository.create_document("finance.txt", domains=["Finance"])
    await permissions.grant_access(hr_doc.id, "user-1")
    await permissions.grant_access(finance_doc.id, "user-1")

    from app.models.document import Chunk

    embedding = [0.1] * 1536
    await repository.save_chunks(
        [
            Chunk(document_id=hr_doc.id, chunk_index=0, text="vacation policy details", embedding=embedding),
            Chunk(document_id=finance_doc.id, chunk_index=0, text="vacation budget details", embedding=embedding),
        ]
    )

    results = await repository.find_by_keyword("vacation", "user-1")

    assert {c.document_id for c in results} == {hr_doc.id, finance_doc.id}


async def test_find_similar_chunks_domain_filter_excludes_other_domains(db_session):
    repository = DocumentRepository(db_session)
    permissions = PermissionRepository(db_session)

    hr_doc = await repository.create_document("hr.txt", domains=["HR"])
    finance_doc = await repository.create_document("finance.txt", domains=["Finance"])
    await permissions.grant_access(hr_doc.id, "user-1")
    await permissions.grant_access(finance_doc.id, "user-1")

    from app.models.document import Chunk

    embedding = [0.1] * 1536
    await repository.save_chunks(
        [
            Chunk(document_id=hr_doc.id, chunk_index=0, text="hr chunk", embedding=embedding),
            Chunk(document_id=finance_doc.id, chunk_index=0, text="finance chunk", embedding=embedding),
        ]
    )

    results = await repository.find_similar_chunks(embedding, "user-1", domain="HR")

    assert [c.document_id for c in results] == [hr_doc.id]


async def test_list_domains_for_user_returns_distinct_domains_across_accessible_documents(db_session):
    repository = DocumentRepository(db_session)
    permissions = PermissionRepository(db_session)

    doc_a = await repository.create_document("a.txt", domains=["HR", "Onboarding"])
    doc_b = await repository.create_document("b.txt", domains=["HR"])
    doc_c = await repository.create_document("c.txt", domains=["Finance"])
    await permissions.grant_access(doc_a.id, "user-1")
    await permissions.grant_access(doc_b.id, "user-1")
    # user-1 never gets access to doc_c — its "Finance" domain should not appear.

    domains = await repository.list_domains_for_user("user-1")

    assert set(domains) == {"HR", "Onboarding"}


async def test_list_domains_for_user_ignores_untagged_documents(db_session):
    repository = DocumentRepository(db_session)
    permissions = PermissionRepository(db_session)

    doc = await repository.create_document("untagged.txt")
    await permissions.grant_access(doc.id, "user-1")

    domains = await repository.list_domains_for_user("user-1")

    assert domains == []


async def test_delete_document_cascades_chunks_and_permission_grants(db_session):
    """Deleting a document must remove its chunks and access grants too, not just the row —
    a leftover chunk or grant pointing at a deleted document would be a real data-integrity gap.
    """
    repository = DocumentRepository(db_session)
    permissions = PermissionRepository(db_session)

    document = await repository.create_document("handbook.pdf")
    await permissions.grant_access(document.id, "user-1")

    from sqlalchemy import select

    from app.models.document import Chunk
    from app.models.document_permission import DocumentPermission

    await repository.save_chunks(
        [Chunk(document_id=document.id, chunk_index=0, text="a chunk", embedding=[0.1] * 1536)]
    )

    await repository.delete_document(document)

    assert await repository.get_by_id(document.id) is None

    remaining_chunks = await db_session.execute(
        select(Chunk).where(Chunk.document_id == document.id)
    )
    assert remaining_chunks.scalars().all() == []

    remaining_permissions = await db_session.execute(
        select(DocumentPermission).where(DocumentPermission.document_id == document.id)
    )
    assert remaining_permissions.scalars().all() == []
