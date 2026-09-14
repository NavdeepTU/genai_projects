import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.middleware import get_correlation_id, get_current_tenant_id, get_current_user_id
from app.models.conversation import (
    ConversationDetailResponse,
    ConversationListItem,
    ConversationListResponse,
    TurnResponse,
)
from app.repositories.audit_repository import AuditRepository
from app.repositories.conversation_repository import ConversationRepository
from app.services.conversation_deletion_service import ConversationDeletionService

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


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a conversation completely — its turns and its database rows.

    User-scoped exactly like viewing or listing (ADR-046): only the user
    who started a conversation can delete it, since conversations were
    never shared the way documents are.
    """
    user_id = get_current_user_id()
    repository = ConversationRepository(db)
    conversation = await repository.get_conversation_for_user(conversation_id, user_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    service = ConversationDeletionService(repository)
    try:
        await service.delete_conversation(conversation)
    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Couldn't delete the conversation. Please try again in a moment.",
        ) from None

    await AuditRepository(db).log_action(
        correlation_id=get_correlation_id(),
        action="conversation_deleted",
        resource_type="conversation",
        resource_id=str(conversation_id),
        tenant_id=get_current_tenant_id(),
        user_id=user_id,
    )

    return Response(status_code=204)
