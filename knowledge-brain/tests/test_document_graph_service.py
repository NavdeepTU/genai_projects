from unittest.mock import AsyncMock, patch

from app.models.document import Chunk
from app.repositories.document_repository import DocumentRepository
from app.repositories.tenant_repository import TenantRepository
from app.services.document_graph_service import DocumentGraphService


async def _tenant_id(db_session, name: str):
    tenant = await TenantRepository(db_session).create_tenant(name)
    return tenant.id


async def test_build_references_creates_an_edge_for_a_same_tenant_match(db_session):
    """A mention that matches another document in the same tenant should link the two."""
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session, "Acme")

    source = await repository.create_document("policy-overview.txt", tenant_id)
    target = await repository.create_document("expense-policy.txt", tenant_id)
    await repository.save_chunks(
        [Chunk(document_id=target.id, chunk_index=0, text="expense policy details", embedding=[0.1] * 1536)]
    )

    graph_repository = AsyncMock()
    service = DocumentGraphService(repository, graph_repository)

    with patch(
        "app.services.document_graph_service.extract_references",
        new=AsyncMock(return_value=["expense policy"]),
    ):
        await service.build_references(source, "See the expense policy for details.")

    graph_repository.create_reference.assert_awaited_once_with(str(source.id), str(target.id))


async def test_build_references_never_links_across_tenants(db_session):
    """The ADR-046 fix: a mention matching another tenant's document must never create
    a reference edge — that edge is exactly what would let one tenant's answer pull in
    graph context from a document it has no access to (see RetrievalService._graph_context_node).
    """
    repository = DocumentRepository(db_session)
    tenant_a = await _tenant_id(db_session, "Acme")
    tenant_b = await _tenant_id(db_session, "Globex")

    source = await repository.create_document("policy-overview.txt", tenant_a)
    other_tenants_document = await repository.create_document("expense-policy.txt", tenant_b)
    await repository.save_chunks(
        [
            Chunk(
                document_id=other_tenants_document.id,
                chunk_index=0,
                text="expense policy details",
                embedding=[0.1] * 1536,
            )
        ]
    )

    graph_repository = AsyncMock()
    service = DocumentGraphService(repository, graph_repository)

    with patch(
        "app.services.document_graph_service.extract_references",
        new=AsyncMock(return_value=["expense policy"]),
    ):
        await service.build_references(source, "See the expense policy for details.")

    graph_repository.create_reference.assert_not_awaited()


async def test_build_references_does_nothing_when_no_mentions_are_extracted(db_session):
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session, "Acme")
    source = await repository.create_document("standalone.txt", tenant_id)

    graph_repository = AsyncMock()
    service = DocumentGraphService(repository, graph_repository)

    with patch(
        "app.services.document_graph_service.extract_references", new=AsyncMock(return_value=[])
    ):
        await service.build_references(source, "Nothing to see here.")

    graph_repository.create_reference.assert_not_awaited()


async def test_build_references_ignores_a_match_that_is_the_document_itself(db_session):
    """A document mentioning its own filename/content shouldn't create a self-referencing edge."""
    repository = DocumentRepository(db_session)
    tenant_id = await _tenant_id(db_session, "Acme")
    source = await repository.create_document("self-mention.txt", tenant_id)
    await repository.save_chunks(
        [Chunk(document_id=source.id, chunk_index=0, text="expense policy details", embedding=[0.1] * 1536)]
    )

    graph_repository = AsyncMock()
    service = DocumentGraphService(repository, graph_repository)

    with patch(
        "app.services.document_graph_service.extract_references",
        new=AsyncMock(return_value=["expense policy"]),
    ):
        await service.build_references(source, "See the expense policy above.")

    graph_repository.create_reference.assert_not_awaited()
