import logging

from langsmith.wrappers import wrap_openai
from openai import AsyncOpenAI, OpenAIError

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
# See embedding.py for what wrap_openai actually does — same reasoning here.
client = wrap_openai(AsyncOpenAI(api_key=settings.openai_api_key))
circuit_breaker = CircuitBreaker(name="moderation")


async def check_moderation(text: str) -> bool:
    """Ask OpenAI's Moderation API whether this text is unsafe (hate, violence, etc.).

    A purpose-built classifier, not an LLM being asked to reason — fast,
    cheap, and it only ever answers the categories it was trained on.
    It has no idea what a "prompt injection" even is, which is exactly
    why injection_detection.py exists as a separate check.
    """
    try:
        response = await circuit_breaker.call(
            lambda: client.moderations.create(model=settings.moderation_model, input=text)
        )
    except OpenAIError:
        logger.exception("Failed to run moderation check")
        raise

    return response.results[0].flagged
