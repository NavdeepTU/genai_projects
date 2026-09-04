import json
import logging

from langsmith.wrappers import wrap_openai
from openai import AsyncOpenAI, OpenAIError

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
client = wrap_openai(AsyncOpenAI(api_key=settings.openai_api_key))
circuit_breaker = CircuitBreaker(name="domain_classification")

SYSTEM_PROMPT = (
    "You are a routing judge for a retrieval-augmented question-answering "
    "system whose documents are tagged with free-text domain labels, such "
    "as departments or topics. You will be given a user's question and the "
    "list of domains that actually have documents available. Decide which "
    "of those domains, if any, this question needs to be answered — a "
    "question can need zero domains (it isn't about any tagged domain, or "
    "no domain applies), exactly one, or more than one if it genuinely "
    "spans multiple areas. Only return domains from the given list, never "
    "invent a new one. Reply with JSON in this exact shape: "
    '{"domains": ["Domain A", "Domain B"]} — an empty list if none apply.'
)


async def classify_domains(question: str, available_domains: list[str]) -> list[str]:
    """Judge which of the available domains, if any, a question needs.

    Returns a subset of available_domains — never a domain outside that
    list, since the judge is explicitly told only those exist. An empty
    available_domains list is a valid input (a user with no domain-tagged
    documents at all): the classifier is still called, and will always
    return an empty list back, so FederatedRetrievalService never needs a
    special case for it.
    """
    try:
        response = await circuit_breaker.call(
            lambda: client.chat.completions.create(
                model=settings.generation_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Available domains: {available_domains}\n\nQuestion: {question}"
                        ),
                    },
                ],
                response_format={"type": "json_object"},
            )
        )
    except OpenAIError:
        logger.exception("Failed to run domain classification")
        raise

    content = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.error("Failed to parse domain classification response as JSON: %s", content)
        return []

    domains = parsed.get("domains", [])
    if not isinstance(domains, list):
        return []
    return [d for d in domains if d in available_domains]
