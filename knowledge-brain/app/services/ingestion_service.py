from app.core.config import get_settings
from app.models.document import Chunk, Document, DocumentStatus
from app.repositories.document_repository import DocumentRepository
from app.services.chunking import chunk_text
from app.services.embedding import embed_chunks
from app.services.extraction import extract_text

settings = get_settings()


class IngestionService:
    """Runs one uploaded file through the whole ingestion pipeline.

    This is the only place that knows the *order* of the pipeline steps.
    Each step itself (extracting, chunking, embedding, saving) lives in
    its own file and knows nothing about the others.
    """

    def __init__(self, repository: DocumentRepository) -> None:
        self.repository = repository

    async def ingest_document(self, filename: str, content: bytes) -> Document:
        """Extract, chunk, embed, and save one uploaded file end to end."""
        document = await self.repository.create_document(filename)

        try:
            text = extract_text(filename, content)
            chunk_texts = chunk_text(text, settings.chunk_size, settings.chunk_overlap)
            embeddings = await embed_chunks(chunk_texts)

            chunks = [
                Chunk(document_id=document.id, chunk_index=i, text=chunk, embedding=embedding)
                for i, (chunk, embedding) in enumerate(zip(chunk_texts, embeddings))
            ]
            await self.repository.save_chunks(chunks)
            await self.repository.update_status(document.id, DocumentStatus.READY)
        except Exception:
            await self.repository.update_status(document.id, DocumentStatus.FAILED)
            raise

        return document
