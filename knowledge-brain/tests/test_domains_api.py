import uuid

from app.api.domains import list_domains
from app.core import middleware
from app.repositories.domain_repository import DomainRepository
from app.repositories.tenant_repository import TenantRepository


async def _tenant_id(db_session, name: str = "Acme") -> uuid.UUID:
    tenant = await TenantRepository(db_session).create_tenant(name)
    return tenant.id


def _set_caller(tenant_id: uuid.UUID):
    return middleware._tenant_id.set(str(tenant_id))


def _reset_caller(token) -> None:
    middleware._tenant_id.reset(token)


async def test_list_domains_returns_every_domain_for_the_callers_tenant(db_session):
    """Available to any signed-in tenant member, not admin-gated — this is
    what populates the upload form's picker."""
    tenant_id = await _tenant_id(db_session)
    await DomainRepository(db_session).create_domain(tenant_id, "HR")
    await DomainRepository(db_session).create_domain(tenant_id, "Finance")

    token = _set_caller(tenant_id)
    try:
        response = await list_domains(db_session)
    finally:
        _reset_caller(token)

    assert sorted(d.name for d in response.domains) == ["Finance", "HR"]


async def test_list_domains_excludes_other_tenants(db_session):
    tenant_id = await _tenant_id(db_session)
    other_tenant_id = await _tenant_id(db_session, "Globex")
    await DomainRepository(db_session).create_domain(other_tenant_id, "Finance")

    token = _set_caller(tenant_id)
    try:
        response = await list_domains(db_session)
    finally:
        _reset_caller(token)

    assert response.domains == []
