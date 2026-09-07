from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from azure.core.exceptions import AzureError, ResourceExistsError, ResourceNotFoundError

from app.core import blob_storage


def test_build_client_uses_the_connection_string_when_one_is_set():
    """Local development against Azurite — see .env.example."""
    with (
        patch.object(blob_storage.settings, "azure_storage_connection_string", "fake-conn-str"),
        patch("app.core.blob_storage.BlobServiceClient.from_connection_string") as mock_from_conn,
    ):
        blob_storage._build_client()

    mock_from_conn.assert_called_once_with("fake-conn-str")


def test_build_client_uses_managed_identity_when_no_connection_string_is_set():
    """The real deployment — no key anywhere in this app's configuration."""
    with (
        patch.object(blob_storage.settings, "azure_storage_connection_string", None),
        patch.object(
            blob_storage.settings, "azure_storage_account_url", "https://x.blob.core.windows.net"
        ),
        patch("app.core.blob_storage.DefaultAzureCredential") as mock_credential,
        patch("app.core.blob_storage.BlobServiceClient") as mock_client_cls,
    ):
        blob_storage._build_client()

    mock_client_cls.assert_called_once_with(
        "https://x.blob.core.windows.net", credential=mock_credential.return_value
    )


def test_build_client_raises_when_neither_is_configured():
    with (
        patch.object(blob_storage.settings, "azure_storage_connection_string", None),
        patch.object(blob_storage.settings, "azure_storage_account_url", None),
        pytest.raises(RuntimeError),
    ):
        blob_storage._build_client()


async def test_upload_document_passes_the_content_type_through():
    fake_container = MagicMock()
    fake_container.upload_blob = AsyncMock()

    with patch.object(blob_storage.client, "get_container_client", return_value=fake_container):
        await blob_storage.upload_document("doc-1.pdf", b"file bytes", "application/pdf")

    fake_container.upload_blob.assert_awaited_once()
    args, kwargs = fake_container.upload_blob.call_args
    assert args == ("doc-1.pdf", b"file bytes")
    assert kwargs["overwrite"] is True
    assert kwargs["content_settings"].content_type == "application/pdf"


async def test_upload_document_reraises_on_a_real_azure_failure():
    fake_container = MagicMock()
    fake_container.upload_blob = AsyncMock(side_effect=AzureError("boom"))

    with (
        patch.object(blob_storage.client, "get_container_client", return_value=fake_container),
        pytest.raises(AzureError),
    ):
        await blob_storage.upload_document("doc-1.pdf", b"file bytes", "application/pdf")


async def test_download_document_returns_the_full_bytes():
    fake_stream = AsyncMock()
    fake_stream.readall = AsyncMock(return_value=b"file bytes")
    fake_container = MagicMock()
    fake_container.download_blob = AsyncMock(return_value=fake_stream)

    with patch.object(blob_storage.client, "get_container_client", return_value=fake_container):
        result = await blob_storage.download_document("doc-1.pdf")

    assert result == b"file bytes"


async def test_download_document_reraises_on_a_real_azure_failure():
    fake_container = MagicMock()
    fake_container.download_blob = AsyncMock(side_effect=AzureError("boom"))

    with (
        patch.object(blob_storage.client, "get_container_client", return_value=fake_container),
        pytest.raises(AzureError),
    ):
        await blob_storage.download_document("doc-1.pdf")


async def test_ensure_container_exists_creates_a_missing_container():
    fake_container = MagicMock()
    fake_container.create_container = AsyncMock()

    with patch.object(blob_storage.client, "get_container_client", return_value=fake_container):
        await blob_storage.ensure_container_exists()

    fake_container.create_container.assert_awaited_once()


async def test_ensure_container_exists_is_a_no_op_when_it_already_exists():
    fake_container = MagicMock()
    fake_container.create_container = AsyncMock(side_effect=ResourceExistsError("already exists"))

    with patch.object(blob_storage.client, "get_container_client", return_value=fake_container):
        await blob_storage.ensure_container_exists()  # must not raise


async def test_delete_document_calls_delete_blob():
    fake_container = MagicMock()
    fake_container.delete_blob = AsyncMock()

    with patch.object(blob_storage.client, "get_container_client", return_value=fake_container):
        await blob_storage.delete_document("doc-1.pdf")

    fake_container.delete_blob.assert_awaited_once_with("doc-1.pdf")


async def test_delete_document_is_a_no_op_when_the_blob_is_already_gone():
    fake_container = MagicMock()
    fake_container.delete_blob = AsyncMock(side_effect=ResourceNotFoundError("not found"))

    with patch.object(blob_storage.client, "get_container_client", return_value=fake_container):
        await blob_storage.delete_document("doc-1.pdf")  # must not raise


async def test_delete_document_reraises_on_a_real_azure_failure():
    fake_container = MagicMock()
    fake_container.delete_blob = AsyncMock(side_effect=AzureError("boom"))

    with (
        patch.object(blob_storage.client, "get_container_client", return_value=fake_container),
        pytest.raises(AzureError),
    ):
        await blob_storage.delete_document("doc-1.pdf")
