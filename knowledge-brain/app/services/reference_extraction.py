import json
import logging

from openai import AsyncOpenAI, OpenAIError

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
client = AsyncOpenAI(api_key=settings.openai_api_key)
circuit_breaker = CircuitBreaker(name="openai_reference_extraction")

SYSTEM_PROMPT = (
    "You extract explicit references from a document's text: error codes, "
    "ticket numbers, policy names, or other specific, named things it "
    "mentions that could plausibly be their own document. Do not include "
    "general topics or concepts, only specific named identifiers. Reply "
    'with JSON in this exact shape: {"references": ["ERR-4521"]}. If '
    'there are none, reply with {"references": []}.'
)


async def extract_references(text: str) -> list[str]:
    """Pull explicit, named references out of a document's text."""
    if not text.strip():
        return []

    try:
        response = await circuit_breaker.call(
            lambda: client.chat.completions.create(
                model=settings.generation_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                response_format={"type": "json_object"},
            )
        )
    except OpenAIError:
        logger.exception("Failed to extract references from document text")
        raise

    content = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.error("Failed to parse reference extraction response as JSON: %s", content)
        return []

    references = parsed.get("references", [])
    return references if isinstance(references, list) else []
