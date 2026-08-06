import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from neo4j import AsyncSession as Neo4jAsyncSession
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.circuit_breaker import CircuitOpenError
from app.core.database import get_db
from app.core.graph_database import get_graph_session
from app.core.middleware import get_correlation_id
from app.models.document import DocumentStatus, DocumentUploadResponse
from app.repositories.audit_repository import AuditRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.graph_repository import GraphRepository
from app.services.document_graph_service import DocumentGraphService
from app.services.extraction import extract_text
from app.services.ingestion_service import IngestionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_EXTENSIONS = (".pdf", ".txt")


@router.post("/upload", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    graph_session: Neo4jAsyncSession = Depends(get_graph_session),
) -> DocumentUploadResponse:
    """Accept one uploaded file and run it through the ingestion pipeline."""
    if not file.filename or not file.filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise HTTPException(status_code=400, detail="Only .pdf and .txt files are supported")

    content = await file.read()
    service = IngestionService(DocumentRepository(db))
    document = await service.ingest_document(file.filename, content)

    if document.status == DocumentStatus.READY:
        try:
            text = extract_text(file.filename, content)
            graph_service = DocumentGraphService(DocumentRepository(db), GraphRepository(graph_session))
            await graph_service.build_references(document, text)
        except CircuitOpenError:
            logger.error(
                "Reference extraction unavailable, document uploaded without graph links",
                extra={"correlation_id": get_correlation_id()},
            )

    correlation_id = get_correlation_id()
    await AuditRepository(db).log_action(
        correlation_id=correlation_id,
        action="document_upload",
        resource_type="document",
        resource_id=str(document.id),
        extra_data={"filename": document.filename, "status": document.status.value},
    )

    return DocumentUploadResponse(
        id=document.id,
        filename=document.filename,
        status=document.status,
        correlation_id=correlation_id,
    )
