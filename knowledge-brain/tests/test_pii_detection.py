from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from azure.core.exceptions import HttpResponseError

from app.core.config import get_settings
from app.services.pii_detection import (
    MAX_DOCUMENTS_PER_REQUEST,
    _split_into_documents,
    detect_pii,
)

settings = get_settings()
LIMIT = settings.pii_max_chars_per_document


def _entity_result(categories: list[str]):
    return SimpleNamespace(
        is_error=False, entities=[SimpleNamespace(category=c) for c in categories]
    )


def _error_result(message: str = "boom"):
    return SimpleNamespace(is_error=True, error=SimpleNamespace(message=message))


async def _passthrough(func):
    return await func()


def _bypass_circuit_breaker():
    """Call the wrapped function directly, without touching the module-level
    circuit breaker's own shared failure/success state — these tests care
    about detect_pii's splitting/batching logic, not the breaker itself
    (see test_circuit_breaker.py for that), and the breaker is a singleton
    shared across every test in this process, so a real failure recorded
    here could open it for an unrelated test running later.
    """
    return patch(
        "app.services.pii_detection.circuit_breaker.call",
        new=AsyncMock(side_effect=_passthrough),
    )


# --- _split_into_documents ---


def test_split_returns_a_single_piece_for_short_text():
    assert _split_into_documents("hello world") == ["hello world"]


def test_split_returns_nothing_for_empty_text():
    assert _split_into_documents("") == []


def test_split_merges_short_paragraphs_into_one_piece_when_they_fit_together():
    text = "First paragraph.\n\nSecond paragraph."
    result = _split_into_documents(text)
    assert result == [text]


def test_split_breaks_at_a_paragraph_boundary_once_the_limit_is_exceeded():
    first = "a" * (LIMIT - 10)
    second = "b" * 50
    text = f"{first}\n\n{second}"

    result = _split_into_documents(text)

    assert len(result) == 2
    assert result[0] == first
    assert result[1] == second


def test_split_hard_cuts_a_single_paragraph_longer_than_the_limit():
    """No paragraph break to split on inside one oversized paragraph — the
    only safe fallback is a hard cut every `limit` characters.
    """
    paragraph = "x" * (LIMIT * 2 + 100)

    result = _split_into_documents(paragraph)

    assert len(result) == 3
    assert result[0] == paragraph[:LIMIT]
    assert result[1] == paragraph[LIMIT : LIMIT * 2]
    assert result[2] == paragraph[LIMIT * 2 :]
    assert "".join(result) == paragraph


def test_split_every_piece_stays_within_the_limit():
    text = "\n\n".join(f"paragraph {i} " + "word " * 200 for i in range(10))

    result = _split_into_documents(text)

    assert all(len(piece) <= LIMIT for piece in result)
    # No content lost or reordered across the split.
    assert "".join(result).replace("\n\n", "") == text.replace("\n\n", "")


# --- detect_pii batching ---


async def test_detect_pii_sends_everything_in_one_batch_when_under_the_cap():
    text = "short document"

    with _bypass_circuit_breaker():
        with patch(
            "app.services.pii_detection.client.recognize_pii_entities",
            new=AsyncMock(return_value=[_entity_result(["Person"])]),
        ) as mock_call:
            result = await detect_pii(text)

    mock_call.assert_awaited_once()
    batch = mock_call.call_args.args[0]
    assert len(batch) == 1
    assert result == ["Person"]


async def test_detect_pii_batches_at_azures_documents_per_request_cap():
    """More pieces than Azure's own 5-per-request cap must go out as
    multiple calls, each capped at MAX_DOCUMENTS_PER_REQUEST. Each paragraph
    is sized close to the per-document limit so no two merge into one piece
    (see test_split_merges_short_paragraphs_into_one_piece_when_they_fit_together
    for the merging behavior this deliberately avoids triggering here).
    """
    paragraphs = [f"paragraph {i} " + "x" * (LIMIT - 20) for i in range(12)]
    text = "\n\n".join(paragraphs)

    with _bypass_circuit_breaker():
        with patch(
            "app.services.pii_detection.client.recognize_pii_entities",
            new=AsyncMock(return_value=[_entity_result([])]),
        ) as mock_call:
            await detect_pii(text)

    call_batches = [call.args[0] for call in mock_call.await_args_list]
    assert len(call_batches) >= 3  # 12 small paragraphs won't all merge into 1 piece
    assert all(len(batch) <= MAX_DOCUMENTS_PER_REQUEST for batch in call_batches)


async def test_detect_pii_unions_categories_found_across_multiple_batches():
    text = "\n\n".join(f"paragraph {i} " + "x" * (LIMIT - 20) for i in range(7))

    responses = [
        [_entity_result(["Person"])] * 5,
        [_entity_result(["USSocialSecurityNumber"])] * 2,
    ]

    with _bypass_circuit_breaker():
        with patch(
            "app.services.pii_detection.client.recognize_pii_entities",
            new=AsyncMock(side_effect=responses),
        ):
            result = await detect_pii(text)

    assert set(result) == {"Person", "USSocialSecurityNumber"}


async def test_detect_pii_returns_no_categories_when_nothing_is_found():
    with _bypass_circuit_breaker():
        with patch(
            "app.services.pii_detection.client.recognize_pii_entities",
            new=AsyncMock(return_value=[_entity_result([])]),
        ):
            result = await detect_pii("nothing sensitive here")

    assert result == []


async def test_detect_pii_raises_when_azure_reports_a_per_document_error():
    with _bypass_circuit_breaker():
        with patch(
            "app.services.pii_detection.client.recognize_pii_entities",
            new=AsyncMock(return_value=[_error_result("could not process")]),
        ):
            with pytest.raises(RuntimeError):
                await detect_pii("some text")


async def test_detect_pii_propagates_an_http_response_error_without_swallowing_it():
    with _bypass_circuit_breaker():
        with patch(
            "app.services.pii_detection.client.recognize_pii_entities",
            new=AsyncMock(side_effect=HttpResponseError("azure is down")),
        ):
            with pytest.raises(HttpResponseError):
                await detect_pii("some text")
