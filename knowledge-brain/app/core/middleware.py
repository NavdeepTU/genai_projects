import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from fastapi import Request, Response

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    """Return the correlation ID for the request currently being handled."""
    return _correlation_id.get()


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
