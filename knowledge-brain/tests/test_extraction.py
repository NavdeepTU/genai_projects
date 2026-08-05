from unittest.mock import MagicMock, patch

import pytest

from app.services.extraction import extract_text


def test_txt_file_returns_decoded_text():
    """A .txt file's bytes are already the text we want — just decode them."""
    text = extract_text("notes.txt", b"hello world")
    assert text == "hello world"


def test_unsupported_extension_raises_error():
    """A file type we don't know how to parse should fail loudly, not silently."""
    with pytest.raises(ValueError):
        extract_text("photo.png", b"not real image bytes")


def test_pdf_joins_multiple_pages_with_newlines():
    """Each page's text should end up on its own line in the final result."""
    fake_page_1 = MagicMock()
    fake_page_1.extract_text.return_value = "Page one text"
    fake_page_2 = MagicMock()
    fake_page_2.extract_text.return_value = "Page two text"

    with patch("app.services.extraction.PdfReader") as mock_reader_class:
        mock_reader_class.return_value.pages = [fake_page_1, fake_page_2]
        text = extract_text("document.pdf", b"fake pdf bytes")

    assert text == "Page one text\nPage two text"


def test_pdf_page_with_no_extractable_text_becomes_empty_string():
    """A scanned/image-only page returns None from pypdf — must not crash the join."""
    fake_page = MagicMock()
    fake_page.extract_text.return_value = None

    with patch("app.services.extraction.PdfReader") as mock_reader_class:
        mock_reader_class.return_value.pages = [fake_page]
        text = extract_text("scanned.pdf", b"fake pdf bytes")

    assert text == ""
