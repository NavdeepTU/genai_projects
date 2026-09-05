import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.middleware import get_correlation_id, get_current_user_id
from app.models.conversation import (
    ConversationDetailResponse,
    ConversationListItem,
    ConversationListResponse,
    TurnResponse,
)
from app.repositories.conversation_repository import ConversationRepository

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=ConversationListResponse)
async def list_conversations(db: AsyncSession = Depends(get_db)) -> ConversationListResponse:
    """Return every conversation the calling user has started, for the sidebar."""
    user_id = get_current_user_id()
    conversations = await ConversationRepository(db).list_conversations_for_user(user_id)
    return ConversationListResponse(
        conversations=[ConversationListItem.model_validate(c) for c in conversations],
        correlation_id=get_correlation_id(),
    )


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ConversationDetailResponse:
    """Return one conversation and every turn in it, to resume where it left off."""
    user_id = get_current_user_id()
    conversation = await ConversationRepository(db).get_conversation_for_user(
        conversation_id, user_id
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return ConversationDetailResponse(
        id=conversation.id,
        title=conversation.title,
        turns=[TurnResponse.model_validate(t) for t in conversation.turns],
        correlation_id=get_correlation_id(),
    )
