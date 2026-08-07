import json
import logging

from openai import AsyncOpenAI, OpenAIError

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
client = AsyncOpenAI(api_key=settings.openai_api_key)
circuit_breaker = CircuitBreaker(name="openai_eval_judge")

FAITHFULNESS_PROMPT = (
    "You judge whether an answer is faithful to its source context — "
    "meaning every claim in the answer is actually supported by the "
    "context, with nothing made up or added. Reply with JSON in this "
    'exact shape: {"faithful": true, "reason": "..."} or '
    '{"faithful": false, "reason": "..."}.'
)

CORRECTNESS_PROMPT = (
    "You judge whether a generated answer conveys the same information "
    "as a reference answer, for a given question. Wording can differ; "
    "the facts must match. Reply with JSON in this exact shape: "
    '{"correct": true, "reason": "..."} or {"correct": false, "reason": "..."}.'
)


async def _ask_judge(system_prompt: str, user_content: str) -> dict:
    try:
        response = await circuit_breaker.call(
            lambda: client.chat.completions.create(
                model=settings.generation_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
            )
        )
    except OpenAIError:
        logger.exception("Eval judge call failed")
        raise

    content = response.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.error("Failed to parse judge response as JSON: %s", content)
        return {}


async def judge_faithfulness(answer: str, context_chunks: list[str]) -> bool:
    """Judge whether an answer only claims things its retrieved context supports."""
    context = "\n\n".join(context_chunks)
    result = await _ask_judge(
        FAITHFULNESS_PROMPT, f"Context:\n{context}\n\nAnswer to judge:\n{answer}"
    )
    return bool(result.get("faithful", False))


async def judge_correctness(question: str, answer: str, reference_answer: str) -> bool:
    """Judge whether a generated answer matches the reference answer's facts."""
    result = await _ask_judge(
        CORRECTNESS_PROMPT,
        f"Question: {question}\n\nReference answer: {reference_answer}\n\nGenerated answer: {answer}",
    )
    return bool(result.get("correct", False))
