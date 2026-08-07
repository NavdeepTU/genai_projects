import secrets

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_settings


class ApiKeyMiddleware:
    """Reject any request to the MCP server that doesn't carry the correct shared secret.

    Written as raw ASGI middleware, not Starlette's BaseHTTPMiddleware —
    BaseHTTPMiddleware runs the wrapped app in a separate task and
    buffers its response, which breaks the MCP server's long-lived
    streaming responses. Raw ASGI middleware forwards receive/send
    straight through, so nothing sits between the client and the stream.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        provided_key = request.headers.get("x-api-key", "")
        expected_key = get_settings().mcp_api_key

        if not secrets.compare_digest(provided_key, expected_key):
            response = JSONResponse({"detail": "Invalid or missing API key"}, status_code=401)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
