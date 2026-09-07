import logging

from azure.core.exceptions import AzureError, ResourceExistsError, ResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob import ContentSettings
from azure.storage.blob.aio import BlobServiceClient

from app.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
circuit_breaker = CircuitBreaker(name="blob_storage")


def _build_client() -> BlobServiceClient:
    """Build the Blob Storage client for whichever environment this is running in (ADR-044).

    Locally, azure_storage_connection_string points at Azurite, the Blob
    Storage emulator — a real connection string, but not a real secret,
    since every Azurite installation everywhere shares the same fixed,
    publicly-documented development account key. In the real deployment,
    no connection string is set at all: the backend authenticates
    directly against azure_storage_account_url using its own Managed
    Identity, so no storage key exists anywhere in this app's config.
    """
    if settings.azure_storage_connection_string:
        return BlobServiceClient.from_connection_string(settings.azure_storage_connection_string)
    if settings.azure_storage_account_url:
        return BlobServiceClient(
            settings.azure_storage_account_url, credential=DefaultAzureCredential()
        )
    raise RuntimeError(
        "Neither azure_storage_connection_string nor azure_storage_account_url is set"
    )


client = _build_client()


async def ensure_container_exists() -> None:
    """Create the blob container if it doesn't exist yet — local development only.

    In the real deployment, Terraform provisions the container ahead of
    time (see infra/storage.tf), and the backend's Managed Identity is
    only granted permission to read and write blobs inside it, not to
    create one. Locally against Azurite, nothing else ever creates it,
    so the app does this once at startup instead — see app/main.py.
    """
    container = client.get_container_client(settings.azure_storage_container_name)
    try:
        await container.create_container()
    except ResourceExistsError:
        pass


async def upload_document(blob_name: str, content: bytes, content_type: str) -> None:
    """Save one document's raw bytes to Blob Storage, so it can be viewed later.

    This function has no fallback of its own — it logs and re-raises on
    failure. IngestionService, its caller, is what decides a failed
    upload shouldn't fail the whole document upload, only mean that
    document has nothing to view.
    """
    container = client.get_container_client(settings.azure_storage_container_name)
    try:
        await circuit_breaker.call(
            lambda: container.upload_blob(
                blob_name,
                content,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type),
            )
        )
    except (CircuitOpenError, AzureError):
        logger.exception("Failed to upload document blob %s", blob_name)
        raise


async def download_document(blob_name: str) -> bytes:
    """Fetch one document's raw bytes back out, to serve it for viewing."""
    container = client.get_container_client(settings.azure_storage_container_name)
    try:
        stream = await circuit_breaker.call(lambda: container.download_blob(blob_name))
        return await stream.readall()
    except (CircuitOpenError, AzureError):
        logger.exception("Failed to download document blob %s", blob_name)
        raise


async def delete_document(blob_name: str) -> None:
    """Delete one document's blob (ADR-045).

    Not an error if it's already gone — delete_blob(..., delete_snapshots="include")
    still raises ResourceNotFoundError for a genuinely missing blob, so
    that specific case is swallowed here: the caller wants the file gone,
    and it already is.
    """
    container = client.get_container_client(settings.azure_storage_container_name)
    try:
        await circuit_breaker.call(lambda: container.delete_blob(blob_name))
    except ResourceNotFoundError:
        return
    except (CircuitOpenError, AzureError):
        logger.exception("Failed to delete document blob %s", blob_name)
        raise
