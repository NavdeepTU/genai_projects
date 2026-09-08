import secrets
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from fastapi import Request, Response
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.repositories.audit_repository import AuditRepository
from app.repositories.session_repository import SessionRepository
from app.repositories.user_repository import UserRepository

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_user_id: ContextVar[str] = ContextVar("user_id", default="")
_tenant_id: ContextVar[str] = ContextVar("tenant_id", default="")

SESSION_COOKIE_NAME = "session_token"

# Paths that must stay reachable without an identity — Swagger UI and its
# schema are for browsing the API's shape, not calling it.
PUBLIC_PATHS = {"/docs", "/openapi.json", "/redoc"}

# Signup and login are how a caller gets a session in the first place —
# requiring one to reach them would be a contradiction. /tenants is
# exempt for the same reason (ADR-046): the signup form needs the list
# of registered tenants to populate its picker, before any session
# exists to prove an identity with. All three still pass through
# gateway_secret_middleware unchanged; only the identity check below is
# skipped for them.
AUTH_EXEMPT_PATHS = {"/auth/signup", "/auth/login", "/tenants"}

# MCP clients authenticate with a shared X-API-Key (see app/mcp/auth.py)
# plus a self-asserted X-User-Id, a deliberately separate trust model
# from the browser-facing session cookie below — an MCP client isn't a
# browser and can't hold a cookie-based session the same way. Real auth
# for REST does not extend to MCP in this pass; that's new scope, not
# migration.
MCP_PATH_PREFIX = "/mcp"


def get_correlation_id() -> str:
    """Return the correlation ID for the request currently being handled."""
    return _correlation_id.get()


def get_current_user_id() -> str:
    """Return the user ID for the request currently being handled."""
    return _user_id.get()


def get_current_tenant_id() -> str:
    """Return the tenant ID for the request currently being handled (ADR-046).

    This is the actual document-access boundary now — every document
    search/list/view/delete call is scoped by this, not by user_id
    directly. user_id still flows separately for identity, conversation
    ownership, and audit attribution.
    """
    return _tenant_id.get()


async def correlation_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Attach a correlation ID to every request, and echo it in the response.

    We reuse an incoming X-Correlation-ID header if the caller already sent
    one (e.g. a request forwarded from another internal service), so a
    single request can be traced across multiple systems using one ID.
    """
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    token = _correlation_id.set(correlation_id)
    try:
        response = await call_next(request)
    finally:
        _correlation_id.reset(token)

    response.headers["X-Correlation-ID"] = correlation_id
    return response


async def _reject_unauthenticated(request: Request, reason: str) -> JSONResponse:
    async with AsyncSessionLocal() as session:
        await AuditRepository(session).log_action(
            correlation_id=get_correlation_id(),
            action="access_denied",
            resource_type="request",
            resource_id=get_correlation_id(),
            extra_data={"path": request.url.path, "reason": reason},
        )
    return JSONResponse({"detail": "Authentication required"}, status_code=401)


async def user_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Attach the caller's identity — and, since ADR-046, their tenant — to every request.

    Two different callers, two different trust models, checked here:

    - MCP clients (paths under /mcp) authenticate with a shared API key
      (app/mcp/auth.py) plus a self-asserted X-User-Id header. That
      header alone used to be enough; now it must also match a real
      user account, since every document-access call needs a real
      tenant_id to scope to, and a made-up id has none. This is a real
      hardening this feature happened to require, not new scope sought
      out on its own.
    - Everyone else (the REST API, used by the browser frontend) must
      present a session cookie that actually exists, unexpired, in the
      database.

    Either way, a request that can't prove who it is — or whose identity
    doesn't resolve to a real account with a real tenant — gets rejected
    outright rather than proceeding as some unknown caller.
    """
    path = request.url.path
    if path in PUBLIC_PATHS or path in AUTH_EXEMPT_PATHS:
        return await call_next(request)

    if path.startswith(MCP_PATH_PREFIX):
        header_user_id = request.headers.get("X-User-Id")
        if not header_user_id:
            return await _reject_unauthenticated(request, "missing X-User-Id header")

        try:
            parsed_user_id = uuid.UUID(header_user_id)
        except ValueError:
            return await _reject_unauthenticated(request, "X-User-Id is not a valid user id")

        async with AsyncSessionLocal() as db_session:
            user = await UserRepository(db_session).get_user_by_id(parsed_user_id)

        if user is None:
            return await _reject_unauthenticated(request, "X-User-Id does not match a real account")

        user_token = _user_id.set(str(user.id))
        tenant_token = _tenant_id.set(str(user.tenant_id))
        try:
            response = await call_next(request)
        finally:
            _user_id.reset(user_token)
            _tenant_id.reset(tenant_token)
        return response

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return await _reject_unauthenticated(request, "missing session cookie")

    async with AsyncSessionLocal() as db_session:
        user = await SessionRepository(db_session).get_user_by_token(session_token)

    if user is None:
        return await _reject_unauthenticated(request, "invalid or expired session")

    user_token = _user_id.set(str(user.id))
    tenant_token = _tenant_id.set(str(user.tenant_id))
    try:
        response = await call_next(request)
    finally:
        _user_id.reset(user_token)
        _tenant_id.reset(tenant_token)

    return response


async def gateway_secret_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Reject any request that didn't pass through API Management.

    APIM stamps every request it forwards with this header, using a value
    only it and this app know — stored in Key Vault, read by each side
    through its own managed identity, never hardcoded anywhere. A request
    missing it, or carrying the wrong value, didn't come through the
    gateway. This is the one real access control on this backend today —
    Consumption tier APIM has no static IP to restrict network access to
    (see ADR-026), so this header is the only thing standing between the
    public internet and the app.
    """
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)

    provided_secret = request.headers.get("X-Gateway-Secret", "")
    expected_secret = get_settings().apim_gateway_secret

    if not secrets.compare_digest(provided_secret, expected_secret):
        async with AsyncSessionLocal() as session:
            await AuditRepository(session).log_action(
                correlation_id=get_correlation_id(),
                action="access_denied",
                resource_type="request",
                resource_id=get_correlation_id(),
                extra_data={"path": request.url.path, "reason": "missing or invalid gateway secret"},
            )
        return JSONResponse(
            {"detail": "Request did not come through the API gateway"}, status_code=401
        )

    return await call_next(request)
