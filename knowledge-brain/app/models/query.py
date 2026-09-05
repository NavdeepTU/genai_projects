import uuid

from pydantic import BaseModel


class QueryRequest(BaseModel):
    """A user's question sent to the /query endpoint.

    conversation_id is omitted (or None) to start a new conversation —
    the route creates one and hands its id back in the response. Given,
    it must belong to the calling user; a stranger's id is treated the
    same as a nonexistent one, not distinguished for them.
    """

    question: str
    conversation_id: uuid.UUID | None = None


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
    conversation_id: uuid.UUID
    correlation_id: str
