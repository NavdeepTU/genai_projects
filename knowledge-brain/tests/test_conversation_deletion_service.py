import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.services.conversation_deletion_service import ConversationDeletionService


def _conversation():
    conversation = AsyncMock()
    conversation.id = uuid.uuid4()
    return conversation


def _service():
    repository = AsyncMock()
    return ConversationDeletionService(repository), repository


async def test_delete_conversation_clears_the_cache_and_removes_the_row():
    service, repository = _service()
    conversation = _conversation()

    with patch(
        "app.services.conversation_deletion_service.invalidate_recent_turns", new=AsyncMock()
    ) as mock_invalidate:
        await service.delete_conversation(conversation)

    mock_invalidate.assert_awaited_once_with(str(conversation.id))
    repository.delete_conversation.assert_awaited_once_with(conversation)


async def test_delete_conversation_propagates_a_database_failure():
    """Unlike the cache clear, the database delete is the one part that must actually succeed."""
    service, repository = _service()
    conversation = _conversation()
    repository.delete_conversation = AsyncMock(side_effect=RuntimeError("db is down"))

    with patch(
        "app.services.conversation_deletion_service.invalidate_recent_turns", new=AsyncMock()
    ):
        with pytest.raises(RuntimeError):
            await service.delete_conversation(conversation)
