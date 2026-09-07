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


class StreamChunkEvent(BaseModel):
    """One sentence-sized piece of a streamed answer, already checked and safe to show."""

    text: str


class StreamTtftEvent(BaseModel):
    """Time from request start to the first visible content — sent once per stream."""

    ms: float


class StreamRetractEvent(BaseModel):
    """Tells the client to erase whatever it has shown so far — the answer was withdrawn."""

    reason: str


class StreamDoneEvent(BaseModel):
    """The final, authoritative state of a streamed answer — always the last event sent."""

    answer: str
    blocked: bool
    block_reason: str | None
    sources: list[QuerySource]
    confidence: float | None
    domains_used: list[str]
    partial: bool
    conversation_id: uuid.UUID
    correlation_id: str


class StreamErrorEvent(BaseModel):
    """An unexpected failure after the stream had already started — e.g. the turn couldn't be saved."""

    detail: str
