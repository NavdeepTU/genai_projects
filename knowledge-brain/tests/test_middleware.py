import uuid
from unittest.mock import patch

from sqlalchemy import delete
from starlette.requests import Request
from starlette.responses import Response

from app.core import middleware
from app.core.middleware import user_id_middleware
from app.core.redis_cache import get_cached_identity
from app.models.user import User
from app.repositories.session_repository import SessionRepository
from app.repositories.tenant_repository import TenantRepository
from app.repositories.user_repository import UserRepository

# user_id_middleware opens its own AsyncSessionLocal() rather than accepting
# an injected session — the same shape MCP's tools have, tested the same way
# (see tests/test_mcp_server.py): stand in for it with the test's db_session.


class _FakeAsyncSessionLocal:
    """Stands in for AsyncSessionLocal: `async with AsyncSessionLocal() as db`."""

    def __init__(self, session) -> None:
        self._session = session

    def __call__(self):
        return self

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *args) -> bool:
        return False


def _request(
    path: str, *, cookie: str | None = None, x_user_id: str | None = None
) -> Request:
    headers = []
    if cookie is not None:
        headers.append((b"cookie", f"{middleware.SESSION_COOKIE_NAME}={cookie}".encode()))
    if x_user_id is not None:
        headers.append((b"x-user-id", x_user_id.encode()))
    scope = {"type": "http", "method": "GET", "path": path, "headers": headers}
    return Request(scope)


async def _call_next(request: Request) -> Response:
    return Response(status_code=200)


async def _tenant_id(db_session) -> uuid.UUID:
    tenant = await TenantRepository(db_session).create_tenant("Acme")
    return tenant.id


async def test_user_id_middleware_resolves_a_real_session_and_caches_it(db_session):
    tenant_id = await _tenant_id(db_session)
    user = await UserRepository(db_session).create_user("alice@example.com", "hashed", tenant_id)
    session = await SessionRepository(db_session).create_session(user.id)
    request = _request("/query", cookie=session.token)

    with patch("app.core.middleware.AsyncSessionLocal", new=_FakeAsyncSessionLocal(db_session)):
        response = await user_id_middleware(request, _call_next)

    assert response.status_code == 200
    cached = await get_cached_identity(session.token)
    assert cached == {"user_id": str(user.id), "tenant_id": str(tenant_id)}


async def test_user_id_middleware_uses_the_cache_instead_of_the_database_on_a_repeat_request(
    db_session,
):
    """Prove the cache is actually used, not just populated: delete the real
    session row after the first request, then confirm a second request with
    the same cookie still succeeds — it can only be reading the cache."""
    tenant_id = await _tenant_id(db_session)
    user = await UserRepository(db_session).create_user("bob@example.com", "hashed", tenant_id)
    session = await SessionRepository(db_session).create_session(user.id)
    request = _request("/query", cookie=session.token)

    with patch("app.core.middleware.AsyncSessionLocal", new=_FakeAsyncSessionLocal(db_session)):
        first = await user_id_middleware(request, _call_next)
        assert first.status_code == 200

        await SessionRepository(db_session).delete_session(session.token)

        second = await user_id_middleware(request, _call_next)

    assert second.status_code == 200


async def test_user_id_middleware_rejects_and_does_not_cache_an_invalid_session(db_session):
    request = _request("/query", cookie="this-token-was-never-real")

    with patch("app.core.middleware.AsyncSessionLocal", new=_FakeAsyncSessionLocal(db_session)):
        response = await user_id_middleware(request, _call_next)

    assert response.status_code == 401
    assert await get_cached_identity("this-token-was-never-real") is None


async def test_user_id_middleware_caches_the_mcp_identity_path_too(db_session):
    """The MCP branch (X-User-Id header, no session cookie) shares the same
    _resolve_identity caching helper — prove it independently of the
    session-cookie path above, the same way each caller type gets its own
    coverage elsewhere in this suite (see tests/test_mcp_server.py)."""
    tenant_id = await _tenant_id(db_session)
    user = await UserRepository(db_session).create_user("mcp-user@example.com", "hashed", tenant_id)
    request = _request("/mcp", x_user_id=str(user.id))

    with patch("app.core.middleware.AsyncSessionLocal", new=_FakeAsyncSessionLocal(db_session)):
        first = await user_id_middleware(request, _call_next)
        assert first.status_code == 200

        await db_session.execute(delete(User).where(User.id == user.id))
        await db_session.commit()

        second = await user_id_middleware(request, _call_next)

    assert second.status_code == 200
    cached = await get_cached_identity(str(user.id))
    assert cached == {"user_id": str(user.id), "tenant_id": str(tenant_id)}
