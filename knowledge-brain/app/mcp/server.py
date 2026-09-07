import base64
import logging

from mcp.server.mcpserver import MCPServer

from app.core.circuit_breaker import CircuitOpenError
from app.core.database import AsyncSessionLocal
from app.core.graph_database import driver as graph_driver
from app.core.middleware import get_correlation_id, get_current_user_id
from app.models.document import DocumentStatus
from app.repositories.audit_repository import AuditRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.graph_repository import GraphRepository
from app.repositories.permission_repository import PermissionRepository
from app.services.document_graph_service import DocumentGraphService
from app.services.extraction import extract_text
from app.services.ingestion_service import IngestionService
from app.services.federated_retrieval_service import FederatedRetrievalService
from app.services.retrieval_service import RetrievalUnavailableError

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
    """Wrap FederatedRetrievalService.run_query() as a tool an MCP client can call directly.

    Same entry point the REST route uses (see ADR-040) — a question
    spanning more than one document domain is handled transparently here
    too, with no separate MCP-specific logic for it.
    """
    user_id = get_current_user_id()
    async with AsyncSessionLocal() as db, graph_driver.session() as graph_session:
        service = FederatedRetrievalService(DocumentRepository(db), GraphRepository(graph_session))

        try:
            result = await service.run_query(question, user_id)
        except (CircuitOpenError, RetrievalUnavailableError):
            return "The knowledge base is temporarily unavailable. Please try again in a moment."

        correlation_id = get_correlation_id()
        audit = AuditRepository(db)
        await audit.log_query_made(
            correlation_id=correlation_id,
            user_id=user_id,
            question=question,
            duration_ms=result.duration_ms,
        )
        if result.blocked:
            await audit.log_answer_blocked(
                correlation_id=correlation_id,
                user_id=user_id,
                question=question,
                block_reason=result.block_reason or "unknown",
            )

        return result.answer


@mcp.tool(
    description=(
        "Upload a document into the knowledge base so future questions can "
        "be answered from it. Only .pdf and .txt files are supported. "
        "content_base64 must be the raw file bytes, base64-encoded — not "
        "plain text — since MCP tool arguments can only carry JSON-safe "
        "strings, not binary data. domains is an optional list of free-text "
        "category tags (e.g. [\"HR\", \"Finance\"]) — set manually, for now."
    )
)
async def upload_document(
    filename: str, content_base64: str, domains: list[str] | None = None
) -> str:
    """Wrap the same ingest-then-link pipeline documents.py uses, for MCP callers."""
    if not filename.lower().endswith(ALLOWED_EXTENSIONS):
        return "Only .pdf and .txt files are supported."

    content = base64.b64decode(content_base64)
    user_id = get_current_user_id()

    async with AsyncSessionLocal() as db, graph_driver.session() as graph_session:
        repository = DocumentRepository(db)
        service = IngestionService(repository, PermissionRepository(db))
        document = await service.create_document(filename, content, user_id, domains)
        await service.process_document(document.id, filename, content)

        correlation_id = get_correlation_id()
        await AuditRepository(db).log_action(
            correlation_id=correlation_id,
            action="document_upload",
            resource_type="document",
            resource_id=str(document.id),
            extra_data={
                "filename": document.filename,
                "status": document.status.value,
                "domains": document.domains,
            },
            user_id=user_id,
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
