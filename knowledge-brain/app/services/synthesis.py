import logging

from langsmith.wrappers import wrap_openai
from openai import AsyncOpenAI, OpenAIError

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
client = wrap_openai(AsyncOpenAI(api_key=settings.openai_api_key))
circuit_breaker = CircuitBreaker(name="synthesis")

SYSTEM_PROMPT = (
    "You are merging answers that were each generated independently by a "
    "domain-specific assistant, working only from documents in its own "
    "domain, into a single answer for the person who asked the original "
    "question. Combine what they found into one coherent answer — don't "
    "just concatenate them. If the domains' answers agree or complement "
    "each other, merge them smoothly. If they genuinely conflict, say so "
    "plainly rather than picking a side silently, and name which domain "
    "said what. If a domain's answer says it doesn't know or found "
    "nothing relevant, you can leave it out of the merged answer entirely."
)


async def synthesize_answers(
    question: str, domain_answers: list[tuple[str, str]], partial: bool
) -> str:
    """Merge one draft answer per domain into a single answer.

    domain_answers is (domain, answer) pairs — each answer already a full,
    independently-generated draft from that domain's own retrieval pass,
    not just a bag of chunks, per the "merges the per-domain answers"
    wording this feature is built to. partial marks that one or more
    domains' retrieval failed and were left out entirely, so the model
    can say plainly that this answer may be incomplete rather than
    presenting it as if every relevant domain had been consulted.
    """
    findings = "\n\n".join(f"[{domain}]\n{answer}" for domain, answer in domain_answers)
    partial_note = (
        "\n\nNote: at least one relevant domain could not be searched right now "
        "and is missing from the findings below — say plainly that this answer "
        "may be incomplete."
        if partial
        else ""
    )
    user_prompt = f"Question: {question}{partial_note}\n\nPer-domain findings:\n{findings}"

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
        logger.exception("Failed to synthesize answer for question: %s", question)
        raise

    return response.choices[0].message.content or ""
