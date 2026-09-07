import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass

from openai import OpenAIError

from app.core.circuit_breaker import CircuitOpenError
from app.core.middleware import get_correlation_id
from app.services.generation import stream_answer
from app.services.injection_detection import check_injection
from app.services.moderation import check_moderation

logger = logging.getLogger(__name__)

# A deliberately simple sentence boundary: text ending in ./!/? followed by
# whitespace (or the end of the buffer). Real sentence segmentation (an
# abbreviation like "Dr." or a decimal like "3.14") isn't handled — an
# honest, named limitation, not a silent one. Good enough for what this
# exists to do: give the moderation check whole thoughts to look at,
# rather than isolated words.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


@dataclass
class StreamChunk:
    """One sentence-sized piece of the answer, already checked and safe to show."""

    text: str


@dataclass
class StreamRetract:
    """The answer must be withdrawn — the client should erase whatever it has shown so far."""

    reason: str


@dataclass
class StreamDone:
    """The full answer streamed successfully; full_text is everything that was actually shown."""

    full_text: str


StreamEvent = StreamChunk | StreamRetract | StreamDone


async def stream_checked_answer(question: str, context_chunks: list[str]) -> AsyncIterator[StreamEvent]:
    """Stream an answer sentence by sentence, moderation-checking each one before it's released.

    Unlike the non-streaming output guardrail, moderation here has no
    companion check to fall back on for a given sentence — it's the only
    signal available for that fragment, so its own unavailability is
    treated as a block, not "no signal, no problem" (see
    _check_moderation_or_block). The injection judge still needs the
    *complete* answer to judge whether it was hijacked by something
    smuggled into a retrieved document — that can only run once
    generation is done, which means it can only retract already-shown
    text, not prevent it from being shown at all (see ADR-043's
    reasoning for why this was chosen over dropping the check entirely).
    """
    buffer = ""
    shown_so_far = ""

    try:
        async for delta in stream_answer(question, context_chunks):
            buffer += delta
            while (match := _SENTENCE_BOUNDARY.search(buffer)) is not None:
                sentence, buffer = buffer[: match.end()], buffer[match.end() :]
                if not await _check_moderation_or_block(sentence):
                    yield StreamRetract(reason="moderation")
                    return
                shown_so_far += sentence
                yield StreamChunk(text=sentence)
    except (CircuitOpenError, OpenAIError):
        logger.error(
            "Streaming generation failed for question: %s",
            question,
            extra={"correlation_id": get_correlation_id()},
        )
        yield StreamRetract(reason="generation_unavailable")
        return

    if buffer:
        if not await _check_moderation_or_block(buffer):
            yield StreamRetract(reason="moderation")
            return
        shown_so_far += buffer
        yield StreamChunk(text=buffer)

    if not await _check_injection_or_block(question, shown_so_far, context_chunks):
        yield StreamRetract(reason="injection")
        return

    yield StreamDone(full_text=shown_so_far)


async def _check_moderation_or_block(text: str) -> bool:
    """Return True if this sentence is safe to show. An unavailable check blocks here —
    there's no second check backing up any individual sentence the way the non-streaming
    output guardrail has two checks to fall back on each other.
    """
    try:
        flagged = await check_moderation(text)
    except (CircuitOpenError, OpenAIError):
        logger.error(
            "Moderation check unavailable mid-stream, blocking rather than guessing",
            extra={"correlation_id": get_correlation_id()},
        )
        return False
    return not flagged


async def _check_injection_or_block(question: str, answer: str, context_chunks: list[str]) -> bool:
    """Return True if the complete answer passes the injection check.

    Availability-aware the same way the non-streaming output guardrail is
    for its moderation+injection pair — but here it's this one check
    alone, since moderation has already cleared every sentence
    individually by this point. An unavailable check is treated as a
    block, matching this project's standing rule that no signal at all
    is never the same claim as a clean answer actually checked.
    """
    try:
        flagged = await check_injection(question, answer, context_chunks)
    except (CircuitOpenError, OpenAIError):
        logger.error(
            "Injection check unavailable after streaming, retracting rather than trusting it",
            extra={"correlation_id": get_correlation_id()},
        )
        return False
    return not flagged
