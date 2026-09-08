import uuid

from app.repositories.tenant_repository import TenantRepository


async def test_create_tenant_returns_a_tenant_with_the_given_name(db_session):
    repository = TenantRepository(db_session)

    tenant = await repository.create_tenant("Acme")

    assert tenant.name == "Acme"
    assert tenant.id is not None


async def test_list_tenants_returns_every_tenant_oldest_first(db_session):
    repository = TenantRepository(db_session)

    first = await repository.create_tenant("Acme")
    second = await repository.create_tenant("Globex")

    tenants = await repository.list_tenants()

    assert [t.id for t in tenants] == [first.id, second.id]


async def test_get_tenant_by_id_returns_none_for_an_unknown_id(db_session):
    repository = TenantRepository(db_session)

    assert await repository.get_tenant_by_id(uuid.uuid4()) is None


async def test_get_tenant_by_id_returns_the_matching_tenant(db_session):
    repository = TenantRepository(db_session)
    tenant = await repository.create_tenant("Acme")

    found = await repository.get_tenant_by_id(tenant.id)

    assert found is not None
    assert found.id == tenant.id


async def test_get_tenant_by_name_returns_none_when_no_tenant_has_that_name(db_session):
    repository = TenantRepository(db_session)

    assert await repository.get_tenant_by_name("Nonexistent") is None


async def test_get_tenant_by_name_returns_the_matching_tenant(db_session):
    repository = TenantRepository(db_session)
    tenant = await repository.create_tenant("Acme")

    found = await repository.get_tenant_by_name("Acme")

    assert found is not None
    assert found.id == tenant.id
