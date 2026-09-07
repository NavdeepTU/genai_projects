import logging
from collections.abc import AsyncIterator

from langsmith.wrappers import wrap_openai
from openai import AsyncOpenAI, OpenAIError

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
# See embedding.py for what wrap_openai actually does — same reasoning here.
client = wrap_openai(AsyncOpenAI(api_key=settings.openai_api_key))
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


async def stream_answer(question: str, context_chunks: list[str]) -> AsyncIterator[str]:
    """Ask the LLM to answer, yielding text as it's produced instead of waiting for all of it.

    Reuses generate_answer's own circuit breaker — this is the exact same
    OpenAI dependency, just called with stream=True, so a failure here
    should count against the same breaker rather than a separate one that
    would only ever protect against the same underlying outage (see
    ADR-040's reasoning against redundant per-variant breakers). Only the
    call that opens the stream is wrapped — once the stream itself is
    open, per-token failures during iteration propagate to the caller
    directly, which is what actually lets it stop cleanly rather than
    retry a connection that's already flowing.
    """
    context = "\n\n".join(context_chunks)
    user_prompt = f"Context:\n{context}\n\nQuestion: {question}"

    try:
        stream = await circuit_breaker.call(
            lambda: client.chat.completions.create(
                model=settings.generation_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                stream=True,
            )
        )
    except OpenAIError:
        logger.exception("Failed to start streaming answer for question: %s", question)
        raise

    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta
