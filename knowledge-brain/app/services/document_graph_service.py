from app.models.document import Document
from app.repositories.document_repository import DocumentRepository
from app.repositories.graph_repository import GraphRepository
from app.services.reference_extraction import extract_references


class DocumentGraphService:
    """Builds explicit reference links between documents after ingestion.

    Reads what a newly-ingested document explicitly mentions, checks
    whether any mention actually matches content in another document,
    and records a REFERENCES edge in the graph for each real match —
    mirroring IngestionService's role, but for relationships instead of
    the document itself.
    """

    def __init__(self, repository: DocumentRepository, graph_repository: GraphRepository) -> None:
        self.repository = repository
        self.graph_repository = graph_repository

    async def build_references(self, document: Document, text: str) -> None:
        """Extract, resolve, and record this document's references to others."""
        mentions = await extract_references(text)

        for mention in mentions:
            matches = await self.repository.find_by_keyword_unrestricted(mention, limit=5)
            other_document_match = next(
                (chunk for chunk in matches if chunk.document_id != document.id), None
            )
            if other_document_match is not None:
                await self.graph_repository.create_reference(
                    str(document.id), str(other_document_match.document_id)
                )
