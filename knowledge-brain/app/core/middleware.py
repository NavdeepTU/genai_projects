import secrets
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from fastapi import Request, Response
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.repositories.audit_repository import AuditRepository

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_user_id: ContextVar[str] = ContextVar("user_id", default="")

# Paths that must stay reachable without an identity — Swagger UI and its
# schema are for browsing the API's shape, not calling it.
PUBLIC_PATHS = {"/docs", "/openapi.json", "/redoc"}


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


async def user_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Attach the caller's identity to every request — required, not invented.

    Unlike a correlation ID, which is safe to generate when missing, a
    missing user ID means we genuinely don't know who's asking — the
    request is rejected outright rather than proceeding as some unknown
    caller, since every downstream permission check depends on this
    being real.
    """
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)

    user_id = request.headers.get("X-User-Id")
    if not user_id:
        async with AsyncSessionLocal() as session:
            await AuditRepository(session).log_action(
                correlation_id=get_correlation_id(),
                action="access_denied",
                resource_type="request",
                resource_id=get_correlation_id(),
                extra_data={"path": request.url.path, "reason": "missing X-User-Id header"},
            )
        return JSONResponse({"detail": "X-User-Id header is required"}, status_code=401)

    token = _user_id.set(user_id)
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
