import pytest

from app.services.chunking import chunk_text


def test_short_text_returns_one_chunk():
    """Text shorter than chunk_size shouldn't be split at all."""
    chunks = chunk_text("one two three", chunk_size=10, chunk_overlap=2)
    assert chunks == ["one two three"]


def test_long_text_splits_into_multiple_chunks():
    """Text longer than chunk_size should be split into more than one piece."""
    words = " ".join(f"word{i}" for i in range(25))
    chunks = chunk_text(words, chunk_size=10, chunk_overlap=2)
    assert len(chunks) > 1


def test_consecutive_chunks_overlap_by_the_configured_amount():
    """The last chunk_overlap words of one chunk should start the next chunk."""
    words = " ".join(f"word{i}" for i in range(10))
    chunks = chunk_text(words, chunk_size=4, chunk_overlap=1)

    first_chunk_words = chunks[0].split()
    second_chunk_words = chunks[1].split()
    assert first_chunk_words[-1] == second_chunk_words[0]


def test_empty_text_returns_no_chunks():
    """Nothing to chunk should produce an empty list, not an error."""
    assert chunk_text("", chunk_size=10, chunk_overlap=2) == []


def test_overlap_larger_than_chunk_size_is_rejected():
    """An overlap >= chunk_size would make chunking loop forever or duplicate everything."""
    with pytest.raises(ValueError):
        chunk_text("some words here", chunk_size=5, chunk_overlap=5)
