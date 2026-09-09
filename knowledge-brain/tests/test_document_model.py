import uuid
from datetime import UTC, datetime

from app.models.document import Document, DocumentListItem, DocumentStatus


def _document(storage_path: str | None) -> Document:
    return Document(
        id=uuid.uuid4(),
        filename="handbook.pdf",
        status=DocumentStatus.READY,
        pii_detected=False,
        uploaded_at=datetime.now(UTC),
        storage_path=storage_path,
    )


def test_has_file_is_false_when_nothing_was_ever_stored():
    document = _document(storage_path=None)

    assert document.has_file is False


def test_has_file_is_true_once_a_storage_path_is_set():
    document = _document(storage_path="doc-1.pdf")

    assert document.has_file is True


def test_document_list_item_exposes_has_file_for_the_frontend():
    """DocumentListItem.model_validate reads has_file straight off the ORM property
    (from_attributes=True) — this is what the Document Library page's "View" link
    vs. "Not viewable" state actually decides on.
    """
    viewable = DocumentListItem.model_validate(_document(storage_path="doc-1.pdf"))
    not_viewable = DocumentListItem.model_validate(_document(storage_path=None))

    assert viewable.has_file is True
    assert not_viewable.has_file is False
