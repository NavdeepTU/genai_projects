import logging

from openai import AsyncOpenAI, OpenAIError

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
client = AsyncOpenAI(api_key=settings.openai_api_key)
circuit_breaker = CircuitBreaker(name="openai_query_rewrite")

SYSTEM_PROMPT = (
    "You rewrite search queries. The user's question just returned zero "
    "results from a document search. Rewrite it into a broader or "
    "differently-phrased search query that is more likely to find "
    "relevant content, while keeping the original intent. Reply with "
    "only the rewritten query, nothing else."
)


async def rewrite_query(question: str) -> str:
    """Rephrase a question that returned no search results into a better one."""
    try:
        response = await circuit_breaker.call(
            lambda: client.chat.completions.create(
                model=settings.generation_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": question},
                ],
            )
        )
    except OpenAIError:
        logger.exception("Failed to rewrite query: %s", question)
        raise

    return response.choices[0].message.content or question
