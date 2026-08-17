import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from neo4j import AsyncSession as Neo4jAsyncSession
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.circuit_breaker import CircuitOpenError
from app.core.database import get_db
from app.core.graph_database import get_graph_session
from app.core.middleware import get_correlation_id, get_current_user_id
from app.models.document import (
    DocumentListItem,
    DocumentListResponse,
    DocumentStatus,
    DocumentUploadResponse,
)
from app.models.document_permission import GrantAccessRequest, GrantAccessResponse
from app.repositories.audit_repository import AuditRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.graph_repository import GraphRepository
from app.repositories.permission_repository import PermissionRepository
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
    user_id = get_current_user_id()
    service = IngestionService(DocumentRepository(db), PermissionRepository(db))
    document = await service.ingest_document(file.filename, content, user_id)

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
        user_id=user_id,
    )

    return DocumentUploadResponse(
        id=document.id,
        filename=document.filename,
        status=document.status,
        correlation_id=correlation_id,
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    """Return every document the calling user has access to, newest first."""
    user_id = get_current_user_id()
    documents = await DocumentRepository(db).list_documents_for_user(user_id)
    return DocumentListResponse(
        documents=[DocumentListItem.model_validate(doc) for doc in documents],
        correlation_id=get_correlation_id(),
    )


@router.post("/{document_id}/access", response_model=GrantAccessResponse, status_code=201)
async def grant_document_access(
    document_id: uuid.UUID,
    body: GrantAccessRequest,
    db: AsyncSession = Depends(get_db),
) -> GrantAccessResponse:
    """Share a document with another user — only someone who already has access can do this."""
    user_id = get_current_user_id()
    permission_repository = PermissionRepository(db)

    if not await permission_repository.has_access(document_id, user_id):
        raise HTTPException(status_code=403, detail="You don't have access to this document")

    await permission_repository.grant_access(document_id, body.user_id)

    correlation_id = get_correlation_id()
    await AuditRepository(db).log_action(
        correlation_id=correlation_id,
        action="permission_granted",
        resource_type="document",
        resource_id=str(document_id),
        extra_data={"granted_to": body.user_id},
        user_id=user_id,
    )

    return GrantAccessResponse(
        document_id=document_id, granted_to=body.user_id, correlation_id=correlation_id
    )
