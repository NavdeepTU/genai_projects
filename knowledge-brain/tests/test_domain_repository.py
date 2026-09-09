import uuid

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.models.domain import Domain, document_domains
from app.repositories.domain_repository import DomainRepository
from app.repositories.tenant_repository import TenantRepository


async def _domain_names_for_document(db_session, document_id) -> list[str]:
    """A plain scalar-column select, not a full Document/Domain entity fetch —
    always reflects real committed data, unlike re-fetching an already
    identity-mapped ORM object after a raw Core UPDATE/DELETE bypassed it."""
    result = await db_session.execute(
        select(Domain.name)
        .join(document_domains, document_domains.c.domain_id == Domain.id)
        .where(document_domains.c.document_id == document_id)
    )
    return sorted(result.scalars().all())


async def _tenant_id(db_session, name: str = "Acme") -> uuid.UUID:
    tenant = await TenantRepository(db_session).create_tenant(name)
    return tenant.id


async def test_create_domain_stores_name_and_tenant(db_session):
    repository = DomainRepository(db_session)
    tenant_id = await _tenant_id(db_session)

    domain = await repository.create_domain(tenant_id, "HR")

    assert domain.name == "HR"
    assert domain.tenant_id == tenant_id


async def test_create_domain_rejects_a_duplicate_name_in_the_same_tenant(db_session):
    repository = DomainRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    await repository.create_domain(tenant_id, "HR")

    try:
        await repository.create_domain(tenant_id, "HR")
        raised = False
    except SQLAlchemyError:
        raised = True
    assert raised


async def test_create_domain_allows_the_same_name_in_different_tenants(db_session):
    repository = DomainRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    other_tenant_id = await _tenant_id(db_session, "Globex")

    await repository.create_domain(tenant_id, "Finance")
    other = await repository.create_domain(other_tenant_id, "Finance")

    assert other.name == "Finance"


async def test_list_for_tenant_includes_a_domain_no_document_uses_yet(db_session):
    """Unlike DocumentRepository.list_domains_for_tenant (only domains in
    use), this is the picker an admin panel or upload form actually shows —
    a brand-new domain must appear immediately, before anything is tagged
    with it."""
    repository = DomainRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    await repository.create_domain(tenant_id, "Legal")

    domains = await repository.list_for_tenant(tenant_id)

    assert [d.name for d in domains] == ["Legal"]


async def test_list_for_tenant_excludes_other_tenants(db_session):
    repository = DomainRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    other_tenant_id = await _tenant_id(db_session, "Globex")
    await repository.create_domain(other_tenant_id, "Finance")

    domains = await repository.list_for_tenant(tenant_id)

    assert domains == []


async def test_get_by_name_for_tenant_is_case_insensitive(db_session):
    """The friendlier pre-check a route uses before insert — "hr" should
    collide with an existing "HR", not create a second near-duplicate."""
    repository = DomainRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    await repository.create_domain(tenant_id, "HR")

    found = await repository.get_by_name_for_tenant(tenant_id, "hr")

    assert found is not None
    assert found.name == "HR"


async def test_rename_domain_keeps_existing_tags_pointing_at_it(db_session):
    from app.repositories.document_repository import DocumentRepository

    domain_repo = DomainRepository(db_session)
    doc_repo = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    domain = await domain_repo.create_domain(tenant_id, "Human Resources")
    document = await doc_repo.create_document("handbook.pdf", tenant_id, domain_ids=[domain.id])

    await domain_repo.rename_domain(domain.id, "HR")
    # Verified via a fresh scalar-column query (_domain_names_for_document),
    # not by re-fetching the Domain/Document entities this same session
    # already loaded — rename_domain is a raw Core UPDATE, and SQLAlchemy's
    # identity map would keep returning the pre-rename in-memory object
    # for a re-fetched *entity*, even though the database itself is
    # correct. Selecting a plain column, not an entity, is never affected
    # by this. A real request never hits this at all: each one gets its
    # own fresh session with nothing stale in memory to begin with.
    assert await _domain_names_for_document(db_session, document.id) == ["HR"]


async def test_merge_domain_reassigns_documents_and_deletes_the_source(db_session):
    from app.repositories.document_repository import DocumentRepository

    domain_repo = DomainRepository(db_session)
    doc_repo = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    source = await domain_repo.create_domain(tenant_id, "Human Resources")
    target = await domain_repo.create_domain(tenant_id, "HR")
    document = await doc_repo.create_document("handbook.pdf", tenant_id, domain_ids=[source.id])

    await domain_repo.merge_domain(source.id, target.id)

    # see test_rename_domain_keeps_existing_tags_pointing_at_it for why this
    # is a fresh scalar-column query, not a re-fetched entity
    assert await _domain_names_for_document(db_session, document.id) == ["HR"]
    assert await domain_repo.get_by_id_for_tenant(source.id, tenant_id) is None


async def test_merge_domain_does_not_duplicate_a_document_already_tagged_with_both(db_session):
    """A document tagged with both source and target must end up tagged
    with target only, not error on a duplicate join-table row."""
    from app.repositories.document_repository import DocumentRepository

    domain_repo = DomainRepository(db_session)
    doc_repo = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    source = await domain_repo.create_domain(tenant_id, "Human Resources")
    target = await domain_repo.create_domain(tenant_id, "HR")
    document = await doc_repo.create_document(
        "handbook.pdf", tenant_id, domain_ids=[source.id, target.id]
    )

    await domain_repo.merge_domain(source.id, target.id)

    # see test_rename_domain_keeps_existing_tags_pointing_at_it for why this
    # is a fresh scalar-column query, not a re-fetched entity
    assert await _domain_names_for_document(db_session, document.id) == ["HR"]


async def test_delete_domain_untags_documents_without_deleting_them(db_session):
    from app.repositories.document_repository import DocumentRepository

    domain_repo = DomainRepository(db_session)
    doc_repo = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session)
    domain = await domain_repo.create_domain(tenant_id, "HR")
    document = await doc_repo.create_document("handbook.pdf", tenant_id, domain_ids=[domain.id])

    await domain_repo.delete_domain(domain.id)

    assert await _domain_names_for_document(db_session, document.id) == []
    # The document itself must survive — only the tag is gone.
    assert await doc_repo.get_by_id(document.id) is not None
