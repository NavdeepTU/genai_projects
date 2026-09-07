from unittest.mock import AsyncMock, patch

from openai import OpenAIError

from app.core.circuit_breaker import CircuitOpenError
from app.services.streaming import StreamChunk, StreamDone, StreamRetract, stream_checked_answer


async def _fake_deltas(pieces: list[str]):
    for piece in pieces:
        yield piece


async def _fake_deltas_that_fail(pieces: list[str], error: Exception):
    for piece in pieces:
        yield piece
    raise error


async def test_streams_each_sentence_then_completes():
    deltas = ["Paris is the capital of France. ", "It has about 2 million people."]

    with (
        patch("app.services.streaming.stream_answer", return_value=_fake_deltas(deltas)),
        patch("app.services.streaming.check_moderation", new=AsyncMock(return_value=False)),
        patch("app.services.streaming.check_injection", new=AsyncMock(return_value=False)),
    ):
        events = [event async for event in stream_checked_answer("What is the capital of France?", ["context"])]

    assert events == [
        StreamChunk(text="Paris is the capital of France. "),
        StreamChunk(text="It has about 2 million people."),
        StreamDone(full_text="Paris is the capital of France. It has about 2 million people."),
    ]


async def test_a_flagged_sentence_retracts_immediately_without_reaching_the_rest():
    deltas = ["This is bad. ", "This part must never be checked or shown."]

    with (
        patch("app.services.streaming.stream_answer", return_value=_fake_deltas(deltas)),
        patch("app.services.streaming.check_moderation", new=AsyncMock(return_value=True)),
    ):
        events = [event async for event in stream_checked_answer("q", ["c"])]

    assert events == [StreamRetract(reason="moderation")]


async def test_moderation_unavailable_blocks_rather_than_guessing():
    deltas = ["A sentence. "]

    with (
        patch("app.services.streaming.stream_answer", return_value=_fake_deltas(deltas)),
        patch(
            "app.services.streaming.check_moderation",
            new=AsyncMock(side_effect=CircuitOpenError("down")),
        ),
    ):
        events = [event async for event in stream_checked_answer("q", ["c"])]

    assert events == [StreamRetract(reason="moderation")]


async def test_generation_failure_mid_stream_retracts_what_was_already_shown():
    with (
        patch(
            "app.services.streaming.stream_answer",
            return_value=_fake_deltas_that_fail(["Partial answer. "], OpenAIError("stream broke")),
        ),
        patch("app.services.streaming.check_moderation", new=AsyncMock(return_value=False)),
    ):
        events = [event async for event in stream_checked_answer("q", ["c"])]

    assert events == [
        StreamChunk(text="Partial answer. "),
        StreamRetract(reason="generation_unavailable"),
    ]


async def test_injection_flag_retracts_after_the_full_answer_was_already_shown():
    deltas = ["Something suspicious."]

    with (
        patch("app.services.streaming.stream_answer", return_value=_fake_deltas(deltas)),
        patch("app.services.streaming.check_moderation", new=AsyncMock(return_value=False)),
        patch("app.services.streaming.check_injection", new=AsyncMock(return_value=True)),
    ):
        events = [event async for event in stream_checked_answer("q", ["c"])]

    assert events == [
        StreamChunk(text="Something suspicious."),
        StreamRetract(reason="injection"),
    ]


async def test_injection_check_unavailable_retracts_rather_than_trusting_it():
    deltas = ["An answer."]

    with (
        patch("app.services.streaming.stream_answer", return_value=_fake_deltas(deltas)),
        patch("app.services.streaming.check_moderation", new=AsyncMock(return_value=False)),
        patch(
            "app.services.streaming.check_injection",
            new=AsyncMock(side_effect=CircuitOpenError("down")),
        ),
    ):
        events = [event async for event in stream_checked_answer("q", ["c"])]

    assert events == [
        StreamChunk(text="An answer."),
        StreamRetract(reason="injection"),
    ]


async def test_a_trailing_sentence_with_no_closing_punctuation_still_gets_checked_and_shown():
    """The last piece of an answer often has no sentence-ending punctuation at all —
    it must still go through moderation and be shown, not silently dropped.
    """
    deltas = ["No terminator here"]

    with (
        patch("app.services.streaming.stream_answer", return_value=_fake_deltas(deltas)),
        patch("app.services.streaming.check_moderation", new=AsyncMock(return_value=False)),
        patch("app.services.streaming.check_injection", new=AsyncMock(return_value=False)),
    ):
        events = [event async for event in stream_checked_answer("q", ["c"])]

    assert events == [
        StreamChunk(text="No terminator here"),
        StreamDone(full_text="No terminator here"),
    ]
