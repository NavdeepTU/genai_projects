import logging
import uuid
from pathlib import Path

from azure.core.exceptions import AzureError

from app.core.blob_storage import upload_document
from app.core.circuit_breaker import CircuitOpenError
from app.core.config import get_settings
from app.models.document import Chunk, Document, DocumentStatus, ProcessingStage
from app.repositories.document_repository import DocumentRepository
from app.services.chunking import chunk_text
from app.services.embedding import embed_chunks
from app.services.extraction import extract_text
from app.services.pii_detection import detect_pii

logger = logging.getLogger(__name__)
settings = get_settings()

# Shared with app/api/documents.py's content-serving route — the same
# mapping tags a blob's Content-Type at upload time and sets the response
# header when it's viewed later, so a document is always served back as
# the same type it was tagged with, not re-derived and risking drift.
CONTENT_TYPES = {".pdf": "application/pdf", ".txt": "text/plain"}


class IngestionService:
    """Runs one uploaded file through the whole ingestion pipeline.

    This is the only place that knows the *order* of the pipeline steps.
    Each step itself (extracting, chunking, embedding, saving) lives in
    its own file and knows nothing about the others.
    """

    def __init__(self, repository: DocumentRepository) -> None:
        self.repository = repository

    async def create_document(
        self, filename: str, content: bytes, tenant_id: uuid.UUID, domains: list[str] | None = None
    ) -> Document:
        """Record a new upload, owned by the uploader's tenant, and save its original file.

        Deliberately still fast enough to finish before the HTTP response
        goes out — the caller has a real document.id to hand back to the
        browser right away, and a single blob upload is far cheaper than
        the extraction/chunking/embedding pipeline that runs afterward in
        the background. domains are set manually at upload, for now — see
        ADR-040. tenant_id is what makes this document visible to every
        other user in the same tenant, with no separate grant needed
        (ADR-046 replaced the old per-user access-grant step this method
        used to do here). Saving the file to Blob Storage (ADR-044) is
        best-effort: an outage there degrades to "this document has
        nothing to view," the same way a down reranker or an unreachable
        Neo4j degrades elsewhere in this project, rather than failing the
        whole upload — the file being viewable later is additive, not
        what this system exists to do.
        """
        document = await self.repository.create_document(filename, tenant_id, domains)

        blob_name = f"{document.id}{Path(filename).suffix.lower()}"
        content_type = CONTENT_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")
        try:
            await upload_document(blob_name, content, content_type)
        except (CircuitOpenError, AzureError):
            logger.error(
                "Blob upload failed for document %s, it will have no viewable file", document.id
            )
            return document

        # set_storage_path fetches the same row through this repository's
        # own session, so SQLAlchemy's identity map means this mutates the
        # exact `document` object above too — no separate assignment needed.
        await self.repository.set_storage_path(document.id, blob_name)
        return document

    async def process_document(self, document_id: uuid.UUID, filename: str, content: bytes) -> None:
        """Run the actual pipeline on an already-created document.

        Meant to be run in the background, after the upload response has
        already been sent — the document row must already exist (via
        create_document) before this is called.
        """
        await self.repository.update_status(document_id, DocumentStatus.PROCESSING)

        try:
            await self.repository.update_processing_stage(document_id, ProcessingStage.EXTRACTING)
            text = extract_text(filename, content)

            await self.repository.update_processing_stage(document_id, ProcessingStage.CHECKING_PII)
            if await detect_pii(text):
                await self.repository.flag_for_review(document_id)
                return

            await self.repository.update_processing_stage(document_id, ProcessingStage.CHUNKING)
            chunk_texts = chunk_text(text, settings.chunk_size, settings.chunk_overlap)

            await self.repository.update_processing_stage(document_id, ProcessingStage.EMBEDDING)
            embeddings = await embed_chunks(chunk_texts)

            chunks = [
                Chunk(document_id=document_id, chunk_index=i, text=chunk, embedding=embedding)
                for i, (chunk, embedding) in enumerate(zip(chunk_texts, embeddings))
            ]

            await self.repository.update_processing_stage(document_id, ProcessingStage.SAVING)
            await self.repository.save_chunks(chunks)
            await self.repository.update_status(document_id, DocumentStatus.READY)
        except Exception as exc:
            await self.repository.mark_failed(document_id, reason=f"{type(exc).__name__}: {exc}")
            raise
