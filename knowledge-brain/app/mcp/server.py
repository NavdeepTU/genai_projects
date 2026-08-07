import base64
import logging

from mcp.server.mcpserver import MCPServer

from app.core.circuit_breaker import CircuitOpenError
from app.core.database import AsyncSessionLocal
from app.core.graph_database import driver as graph_driver
from app.core.middleware import get_correlation_id
from app.models.document import DocumentStatus
from app.repositories.audit_repository import AuditRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.graph_repository import GraphRepository
from app.services.document_graph_service import DocumentGraphService
from app.services.extraction import extract_text
from app.services.ingestion_service import IngestionService
from app.services.retrieval_service import RetrievalService, RetrievalUnavailableError

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = (".pdf", ".txt")

mcp = MCPServer(name="knowledge-brain")


@mcp.tool(
    description=(
        "Answer a question using only the documents already stored in this "
        "knowledge base. Returns a grounded answer drawn from retrieved "
        "text, or an honest statement that the answer isn't known if "
        "nothing relevant is found — never a guess."
    )
)
async def ask_knowledge_base(question: str) -> str:
    """Wrap RetrievalService.answer_question() as a tool an MCP client can call directly."""
    async with AsyncSessionLocal() as db, graph_driver.session() as graph_session:
        service = RetrievalService(DocumentRepository(db), GraphRepository(graph_session))

        try:
            answer = await service.answer_question(question)
        except (CircuitOpenError, RetrievalUnavailableError):
            return "The knowledge base is temporarily unavailable. Please try again in a moment."

        correlation_id = get_correlation_id()
        await AuditRepository(db).log_action(
            correlation_id=correlation_id,
            action="query_made",
            resource_type="query",
            resource_id=correlation_id,
            extra_data={"question": question},
        )

        return answer


@mcp.tool(
    description=(
        "Upload a document into the knowledge base so future questions can "
        "be answered from it. Only .pdf and .txt files are supported. "
        "content_base64 must be the raw file bytes, base64-encoded — not "
        "plain text — since MCP tool arguments can only carry JSON-safe "
        "strings, not binary data."
    )
)
async def upload_document(filename: str, content_base64: str) -> str:
    """Wrap the same ingest-then-link pipeline documents.py uses, for MCP callers."""
    if not filename.lower().endswith(ALLOWED_EXTENSIONS):
        return "Only .pdf and .txt files are supported."

    content = base64.b64decode(content_base64)

    async with AsyncSessionLocal() as db, graph_driver.session() as graph_session:
        service = IngestionService(DocumentRepository(db))
        document = await service.ingest_document(filename, content)

        correlation_id = get_correlation_id()
        await AuditRepository(db).log_action(
            correlation_id=correlation_id,
            action="document_upload",
            resource_type="document",
            resource_id=str(document.id),
            extra_data={"filename": document.filename, "status": document.status.value},
        )

        if document.status == DocumentStatus.READY:
            try:
                text = extract_text(filename, content)
                graph_service = DocumentGraphService(DocumentRepository(db), GraphRepository(graph_session))
                await graph_service.build_references(document, text)
            except CircuitOpenError:
                logger.error(
                    "Reference extraction unavailable, document uploaded without graph links",
                    extra={"correlation_id": get_correlation_id()},
                )

    return f"Uploaded {filename} — status: {document.status.value}"
