import logging

from openai import AsyncOpenAI, OpenAIError

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
client = AsyncOpenAI(api_key=settings.openai_api_key)
circuit_breaker = CircuitBreaker(name="openai_generation")

SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions using only the "
    "provided context. If the answer isn't in the context, say you don't "
    "know rather than guessing."
)


async def generate_answer(question: str, context_chunks: list[str]) -> str:
    """Ask the LLM to answer a question, grounded only in the given chunks."""
    context = "\n\n".join(context_chunks)
    user_prompt = f"Context:\n{context}\n\nQuestion: {question}"

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
        logger.exception("Failed to generate answer for question: %s", question)
        raise

    return response.choices[0].message.content or ""
