from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.observability import enable_tracing

# Must run before any service module below is imported — they each
# create their OpenAI/Voyage client at import time, and tracing needs
# to be armed before any of those clients ever makes a real call.
enable_tracing()

from app.api.admin import router as admin_router
from app.api.analytics import router as analytics_router
from app.api.auth import router as auth_router
from app.api.conversations import router as conversations_router
from app.api.dashboard import router as dashboard_router
from app.api.documents import router as documents_router
from app.api.query import router as query_router
from app.api.query_stream import router as query_stream_router
from app.core.middleware import (
    correlation_id_middleware,
    gateway_secret_middleware,
    user_id_middleware,
)
from app.mcp.auth import ApiKeyMiddleware
from app.mcp.server import mcp

mcp_app = mcp.streamable_http_app(streamable_http_path="/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the MCP server's internal task group alongside our own app.

    Mounting a sub-app with app.mount() doesn't forward FastAPI's startup
    event into it — only this outer lifespan runs automatically. Without
    entering mcp.session_manager.run() here, the MCP server would silently
    never initialize, and every request to /mcp would fail.
    """
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Knowledge Brain", lifespan=lifespan)

app.middleware("http")(user_id_middleware)
app.middleware("http")(gateway_secret_middleware)
app.middleware("http")(correlation_id_middleware)

app.include_router(admin_router)
app.include_router(analytics_router)
app.include_router(auth_router)
app.include_router(conversations_router)
app.include_router(dashboard_router)
app.include_router(documents_router)
app.include_router(query_router)
app.include_router(query_stream_router)

app.mount("/mcp", ApiKeyMiddleware(mcp_app))
