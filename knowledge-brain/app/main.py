from fastapi import FastAPI

from app.api.documents import router as documents_router
from app.api.query import router as query_router
from app.core.middleware import correlation_id_middleware

app = FastAPI(title="Knowledge Brain")

app.middleware("http")(correlation_id_middleware)

app.include_router(documents_router)
app.include_router(query_router)
