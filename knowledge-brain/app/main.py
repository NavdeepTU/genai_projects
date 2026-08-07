from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.documents import router as documents_router
from app.api.query import router as query_router
from app.core.middleware import correlation_id_middleware
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

app.middleware("http")(correlation_id_middleware)

app.include_router(documents_router)
app.include_router(query_router)

app.mount("/mcp", ApiKeyMiddleware(mcp_app))
