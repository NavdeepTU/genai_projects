from pydantic import BaseModel


class QueryRequest(BaseModel):
    """A user's question sent to the /query endpoint."""

    question: str


class QueryResponse(BaseModel):
    """The generated answer sent back to the user."""

    answer: str
