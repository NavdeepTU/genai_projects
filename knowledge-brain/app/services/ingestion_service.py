import uuid

from app.core.config import get_settings
from app.models.document import Chunk, Document, DocumentStatus, ProcessingStage
from app.repositories.document_repository import DocumentRepository
from app.repositories.permission_repository import PermissionRepository
from app.services.chunking import chunk_text
from app.services.embedding import embed_chunks
from app.services.extraction import extract_text
from app.services.pii_detection import detect_pii

settings = get_settings()


class IngestionService:
    """Runs one uploaded file through the whole ingestion pipeline.

    This is the only place that knows the *order* of the pipeline steps.
    Each step itself (extracting, chunking, embedding, saving) lives in
    its own file and knows nothing about the others.
    """

    def __init__(self, repository: DocumentRepository, permission_repository: PermissionRepository) -> None:
        self.repository = repository
        self.permission_repository = permission_repository

    async def create_document(
        self, filename: str, user_id: str, domains: list[str] | None = None
    ) -> Document:
        """Record a new upload and give the uploader access to it.

        Deliberately just this much and nothing more: fast enough to finish
        before the HTTP response goes out, so the caller has a real
        document.id to hand back to the browser right away. domains are
        set manually at upload, for now — see ADR-040.
        """
        document = await self.repository.create_document(filename, domains)
        await self.permission_repository.grant_access(document.id, user_id)
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
