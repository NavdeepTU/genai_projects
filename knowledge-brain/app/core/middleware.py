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

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_user_id: ContextVar[str] = ContextVar("user_id", default="")

SESSION_COOKIE_NAME = "session_token"

# Paths that must stay reachable without an identity — Swagger UI and its
# schema are for browsing the API's shape, not calling it.
PUBLIC_PATHS = {"/docs", "/openapi.json", "/redoc"}

# Signup and login are how a caller gets a session in the first place —
# requiring one to reach them would be a contradiction. Both still pass
# through gateway_secret_middleware unchanged; only the identity check
# below is skipped for these two.
AUTH_EXEMPT_PATHS = {"/auth/signup", "/auth/login"}

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
    """Attach the caller's identity to every request — proven, not self-asserted.

    Two different callers, two different trust models, checked here:

    - MCP clients (paths under /mcp) authenticate with a shared API key
      (app/mcp/auth.py) plus a self-asserted X-User-Id header — unchanged
      from before. They aren't browsers and can't hold a cookie session.
    - Everyone else (the REST API, used by the browser frontend) must
      present a session cookie that actually exists, unexpired, in the
      database. A missing or invalid X-User-Id header used to be enough;
      now the header is gone entirely and a real login is required.

    Either way, a request that can't prove who it is gets rejected
    outright rather than proceeding as some unknown caller, since every
    downstream permission check depends on this being real.
    """
    path = request.url.path
    if path in PUBLIC_PATHS or path in AUTH_EXEMPT_PATHS:
        return await call_next(request)

    if path.startswith(MCP_PATH_PREFIX):
        user_id = request.headers.get("X-User-Id")
        if not user_id:
            return await _reject_unauthenticated(request, "missing X-User-Id header")
        token = _user_id.set(user_id)
        try:
            response = await call_next(request)
        finally:
            _user_id.reset(token)
        return response

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return await _reject_unauthenticated(request, "missing session cookie")

    async with AsyncSessionLocal() as db_session:
        user = await SessionRepository(db_session).get_user_by_token(session_token)

    if user is None:
        return await _reject_unauthenticated(request, "invalid or expired session")

    token = _user_id.set(str(user.id))
    try:
        response = await call_next(request)
    finally:
        _user_id.reset(token)

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
