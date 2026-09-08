import pytest
from pydantic import ValidationError

from app.models.tenant import CreateTenantRequest


def test_create_tenant_request_strips_surrounding_whitespace():
    """Without this, ' Acme' and 'Acme' would be treated as distinct names,
    silently defeating the duplicate-name check (both in TenantRepository
    and the admin route's own pre-check).
    """
    request = CreateTenantRequest(name="  Acme  ")

    assert request.name == "Acme"


def test_create_tenant_request_rejects_an_all_whitespace_name():
    with pytest.raises(ValidationError):
        CreateTenantRequest(name="   ")
