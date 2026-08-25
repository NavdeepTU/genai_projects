import uuid

from pydantic import BaseModel


class QueryRequest(BaseModel):
    """A user's question sent to the /query endpoint."""

    question: str


class QuerySource(BaseModel):
    """One chunk that actually informed the generated answer."""

    document_id: uuid.UUID
    filename: str
    chunk_text: str


class QueryResponse(BaseModel):
    """The generated answer sent back to the user."""

    answer: str
    sources: list[QuerySource]
    confidence: float | None
    correlation_id: str
