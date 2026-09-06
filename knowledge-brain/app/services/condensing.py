import logging
import uuid
from typing import TYPE_CHECKING

from langsmith.wrappers import wrap_openai
from openai import AsyncOpenAI, OpenAIError
from pydantic import ValidationError

from app.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from app.core.config import get_settings
from app.core.middleware import get_correlation_id
from app.core.redis_cache import cache_recent_turns, get_recent_turns
from app.models.conversation import RecentTurn

if TYPE_CHECKING:
    from app.models.conversation import Conversation

logger = logging.getLogger(__name__)

settings = get_settings()
# See embedding.py for what wrap_openai actually does — same reasoning here.
client = wrap_openai(AsyncOpenAI(api_key=settings.openai_api_key))
circuit_breaker = CircuitBreaker(name="condensing")

SYSTEM_PROMPT = (
    "You rewrite follow-up questions in a conversation so they can stand "
    "alone. You will be shown the last few question-and-answer turns of "
    "a conversation, then a new follow-up question that may only make "
    'sense given that context (for example, "what about the other '
    'one"). Rewrite the follow-up into a complete, standalone question '
    "that means the same thing but needs no prior context to "
    "understand. If the follow-up already stands on its own, return it "
    "unchanged. Reply with only the rewritten question, nothing else."
)


async def condense_question(raw_question: str, recent_turns: list[RecentTurn]) -> str:
    """Rewrite a follow-up into a standalone question, using recent turns as context.

    Unlike query_rewriting.py's rewrite (a temporary retry aid — the
    real generation step always uses the true original question, never
    that one), the question this returns *becomes* the real question
    for everything downstream: both retrieval and generation. The raw
    text is preserved only as a record of what was actually typed.

    recent_turns is oldest-first — the *condensed* question from each
    prior turn, not the raw one, since that's the actual standalone
    question that was really answered.
    """
    context = "\n\n".join(f"Q: {turn.question}\nA: {turn.answer}" for turn in recent_turns)
    user_prompt = f"Conversation so far:\n{context}\n\nNew follow-up: {raw_question}"

    try:
        response = await circuit_breaker.call(
            lambda: client.chat.completions.create(
                model=settings.generation_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
        )
    except OpenAIError:
        logger.exception("Failed to condense question: %s", raw_question)
        raise

    if not response.choices:
        logger.error("Condensing response had no choices, using the raw question unrewritten")
        return raw_question

    return response.choices[0].message.content or raw_question


async def _recent_turns(conversation: "Conversation") -> list[RecentTurn]:
    """Return a conversation's recent turns as condensing wants them: Redis first, falling back
    to the conversation's own already-loaded turns (get_conversation_for_user eager-loads them
    for the ownership check, so this never costs a second query).
    """
    cached = await get_recent_turns(str(conversation.id))
    if cached is not None:
        try:
            return [RecentTurn.model_validate(item) for item in cached]
        except ValidationError:
            logger.exception("Cached recent turns had an unexpected shape, falling back")

    return [
        RecentTurn(question=turn.condensed_question, answer=turn.answer)
        for turn in conversation.turns[-settings.condensing_context_turns :]
    ]


async def get_effective_question(
    raw_question: str, conversation: "Conversation | None"
) -> tuple[str, list[RecentTurn]]:
    """Resolve the question that should actually enter the retrieval pipeline.

    Returns (effective_question, recent_turns) — the caller needs
    recent_turns back too, to append the new turn to it and refresh the
    cache once an answer comes back. A brand-new conversation (None)
    has nothing to condense against, so its question always passes
    through unchanged — this is deliberately the one and only place
    that decision gets made, not duplicated at the route level.
    """
    if conversation is None:
        return raw_question, []

    recent_turns = await _recent_turns(conversation)
    if not recent_turns:
        return raw_question, recent_turns

    try:
        condensed = await condense_question(raw_question, recent_turns)
    except (CircuitOpenError, OpenAIError):
        logger.error(
            "Condensing unavailable, using the raw follow-up unrewritten",
            extra={"correlation_id": get_correlation_id()},
        )
        condensed = raw_question

    return condensed, recent_turns


async def update_recent_turns_cache(
    conversation_id: uuid.UUID, recent_turns: list[RecentTurn], new_question: str, new_answer: str
) -> None:
    """Append the newest turn, trim to the configured window, and refresh the cache.

    Called after a turn is saved, with whatever recent_turns
    get_effective_question already returned earlier in the same
    request — so a brand-new conversation (recent_turns == []) seeds
    the cache with just its first turn, and an existing one keeps only
    the most recent condensing_context_turns. Failures are handled
    entirely inside cache_recent_turns; this never raises.
    """
    updated = [turn.model_dump() for turn in recent_turns] + [
        {"question": new_question, "answer": new_answer}
    ]
    await cache_recent_turns(str(conversation_id), updated[-settings.condensing_context_turns :])
