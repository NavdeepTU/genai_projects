from unittest.mock import AsyncMock, patch

import pytest
from openai import OpenAIError

from app.services.generation import stream_answer


class _FakeDelta:
    def __init__(self, content: str | None) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str | None) -> None:
        self.delta = _FakeDelta(content)


class _FakeChunk:
    def __init__(self, content: str | None = None, *, has_choices: bool = True) -> None:
        self.choices = [_FakeChoice(content)] if has_choices else []


async def _fake_stream(chunks: list[_FakeChunk]):
    for chunk in chunks:
        yield chunk


async def test_stream_answer_yields_each_non_empty_delta():
    chunks = [_FakeChunk("Hello"), _FakeChunk(" world"), _FakeChunk(None), _FakeChunk("!")]

    with patch(
        "app.services.generation.circuit_breaker.call", new=AsyncMock(return_value=_fake_stream(chunks))
    ):
        deltas = [delta async for delta in stream_answer("a question", ["some context"])]

    assert deltas == ["Hello", " world", "!"]


async def test_stream_answer_skips_chunks_with_no_choices():
    """A chunk with an empty choices list (seen in real OpenAI streams, e.g. usage-only
    chunks) must be skipped rather than raising an IndexError.
    """
    chunks = [_FakeChunk("first", has_choices=False), _FakeChunk("second")]

    with patch(
        "app.services.generation.circuit_breaker.call", new=AsyncMock(return_value=_fake_stream(chunks))
    ):
        deltas = [delta async for delta in stream_answer("a question", ["some context"])]

    assert deltas == ["second"]


async def test_stream_answer_raises_when_the_stream_cannot_even_open():
    with patch(
        "app.services.generation.circuit_breaker.call", new=AsyncMock(side_effect=OpenAIError("down"))
    ):
        with pytest.raises(OpenAIError):
            async for _ in stream_answer("a question", ["some context"]):
                pass
