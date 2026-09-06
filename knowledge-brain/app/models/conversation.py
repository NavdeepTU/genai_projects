import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import ARRAY, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# How much of a conversation's first question becomes its sidebar title —
# a plain truncation, not an LLM call, since a short label is all a sidebar
# entry needs and this project doesn't pay for a generation call for
# something this cosmetic. See ADR-041.
TITLE_MAX_LENGTH = 60


class Conversation(Base):
    """One conversation thread — a named container for its turns.

    Deliberately no sharing/permission model the way documents have one:
    a conversation belongs to exactly the user who started it, checked by
    a plain equality match in the repository, not a join table.
    """

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(TITLE_MAX_LENGTH))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    turns: Mapped[list["Turn"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        # id as a tiebreaker: two turns created within the same
        # timestamp tick (unlikely, but not impossible) would otherwise
        # have no stable, repeatable order.
        order_by="Turn.created_at, Turn.id",
    )


class Turn(Base):
    """One question-and-answer pair inside a conversation.

    condensed_question holds the actual standalone question condensing
    produced (ADR-042) — equal to raw_question only when there was
    nothing to condense against (a conversation's first turn) or when
    condensing itself was unavailable and the raw question was used as
    a fallback. sources and domains_used are stored as JSONB rather than
    normalized tables, matching AuditLog's own extra_data column: this
    data is written once, read back whole, and never queried by its
    individual fields.
    """

    __tablename__ = "turns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"))
    raw_question: Mapped[str] = mapped_column(Text)
    condensed_question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    sources: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    confidence: Mapped[float | None] = mapped_column(default=None)
    domains_used: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    correlation_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="turns")


class RecentTurn(BaseModel):
    """One prior turn's question and answer, as condensing needs them for context.

    A real model rather than a plain {"question", "answer"} dict, so a
    typo'd key or an unexpected cache shape fails with a clear
    validation error at the boundary instead of a bare KeyError deep
    inside a prompt-building loop.
    """

    question: str
    answer: str


class TurnResponse(BaseModel):
    """One turn as sent to the frontend — a source is a plain dict here.

    Deliberately not reusing QuerySource: that model is typed against a
    live QueryState's chunks, this one is read back from storage, and
    coupling the two would mean a change to one silently constrains the
    other for no real benefit.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    raw_question: str
    condensed_question: str
    answer: str
    sources: list[dict]
    confidence: float | None
    domains_used: list[str]
    created_at: datetime


class ConversationListItem(BaseModel):
    """One conversation's summary, as shown in the sidebar."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    updated_at: datetime


class ConversationListResponse(BaseModel):
    conversations: list[ConversationListItem]
    correlation_id: str


class ConversationDetailResponse(BaseModel):
    """One conversation with every turn, as loaded when resuming it."""

    id: uuid.UUID
    title: str
    turns: list[TurnResponse]
    correlation_id: str
