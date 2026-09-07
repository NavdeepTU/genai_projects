import logging

from azure.core.exceptions import AzureError

from app.core.blob_storage import delete_document as delete_document_blob
from app.core.circuit_breaker import CircuitOpenError
from app.core.middleware import get_correlation_id
from app.models.document import Document
from app.repositories.document_repository import DocumentRepository
from app.repositories.graph_repository import GraphRepository

logger = logging.getLogger(__name__)


class DocumentDeletionService:
    """Removes a document from everywhere this project stores something about it (ADR-045).

    Mirrors DocumentGraphService's role: a small, single-purpose
    orchestrator, not a dumping ground for every document-related
    operation. Blob Storage and the graph are cleaned up best-effort —
    an outage in either degrades to "a leftover file/node still sits
    there," never blocks the deletion itself, the same failure-isolation
    rule this project applies everywhere else an external dependency
    sits in a request's path. The database row is the one part that
    must actually succeed for the document to count as deleted; chunks
    and permission grants cascade with it automatically (see the
    Document.permissions relationship).
    """

    def __init__(self, repository: DocumentRepository, graph_repository: GraphRepository) -> None:
        self.repository = repository
        self.graph_repository = graph_repository

    async def delete_document(self, document: Document) -> None:
        """Delete one document completely — its file, its graph node, and its database rows."""
        if document.storage_path is not None:
            try:
                await delete_document_blob(document.storage_path)
            except (CircuitOpenError, AzureError):
                logger.error(
                    "Blob delete failed for document %s, a leftover file remains in storage",
                    document.id,
                    extra={"correlation_id": get_correlation_id()},
                )

        try:
            await self.graph_repository.delete_document_node(str(document.id))
        except CircuitOpenError:
            logger.error(
                "Graph delete failed for document %s, a leftover node remains in Neo4j",
                document.id,
                extra={"correlation_id": get_correlation_id()},
            )

        await self.repository.delete_document(document)
