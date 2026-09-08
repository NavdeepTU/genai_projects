import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.conversation import Conversation, Turn

logger = logging.getLogger(__name__)


class ConversationRepository:
    """All direct database access for conversations and turns lives here."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_conversation(self, user_id: str, title: str) -> Conversation:
        """Start a new conversation thread, empty of turns."""
        conversation = Conversation(user_id=user_id, title=title)
        self.session.add(conversation)
        try:
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to create conversation for user %s", user_id)
            raise
        await self.session.refresh(conversation)
        return conversation

    async def add_turn(
        self,
        conversation_id: uuid.UUID,
        *,
        raw_question: str,
        condensed_question: str,
        answer: str,
        sources: list[dict],
        confidence: float | None,
        domains_used: list[str],
        correlation_id: str,
    ) -> Turn:
        """Append one question/answer pair, and bump the conversation's own timestamp.

        The timestamp bump is what lets the sidebar list conversations
        most-recently-active-first — a conversation with a new turn should
        float back to the top, not stay wherever it was created.
        """
        turn = Turn(
            conversation_id=conversation_id,
            raw_question=raw_question,
            condensed_question=condensed_question,
            answer=answer,
            sources=sources,
            confidence=confidence,
            domains_used=domains_used,
            correlation_id=correlation_id,
        )
        self.session.add(turn)

        conversation = await self.session.get(Conversation, conversation_id)
        if conversation is not None:
            conversation.updated_at = datetime.now(UTC)

        try:
            await self.session.commit()
        except SQLAlchemyError:
            logger.exception("Failed to add turn to conversation %s", conversation_id)
            raise
        await self.session.refresh(turn)
        return turn

    async def list_conversations_for_user(self, user_id: str) -> list[Conversation]:
        """Return every conversation this user started, most recently active first."""
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
        )
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to list conversations for user %s", user_id)
            raise
        return list(result.scalars().all())

    async def get_conversation_for_user(
        self, conversation_id: uuid.UUID, user_id: str
    ) -> Conversation | None:
        """Return one conversation with its turns, only if this user started it.

        Returns None identically whether the conversation doesn't exist or
        belongs to someone else — the two cases are deliberately
        indistinguishable from outside, same reasoning
        get_document_for_tenant already uses. Conversations stay scoped
        to the individual user, not the tenant (ADR-046) — unlike
        documents, they were never meant to be shared.
        """
        stmt = (
            select(Conversation)
            .options(selectinload(Conversation.turns))
            .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        )
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError:
            logger.exception("Failed to fetch conversation %s for user %s", conversation_id, user_id)
            raise
        return result.scalar_one_or_none()
