from app.core.redis_cache import invalidate_recent_turns
from app.models.conversation import Conversation
from app.repositories.conversation_repository import ConversationRepository


class ConversationDeletionService:
    """Removes a conversation from everywhere this project stores something about it.

    Mirrors DocumentDeletionService's role and failure-isolation rule: the
    Redis cache clear is best-effort (invalidate_recent_turns already
    swallows its own failures, logging and degrading to "a stale entry
    expires on its own TTL" rather than raising) and never blocks the
    deletion itself. The database rows are the one part that must actually
    succeed for the conversation to count as deleted; turns cascade with it
    automatically (see the Conversation.turns relationship).
    """

    def __init__(self, repository: ConversationRepository) -> None:
        self.repository = repository

    async def delete_conversation(self, conversation: Conversation) -> None:
        """Delete one conversation completely — its cache entry and its database rows."""
        await invalidate_recent_turns(str(conversation.id))
        await self.repository.delete_conversation(conversation)
