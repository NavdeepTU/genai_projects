import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.circuit_breaker import CircuitOpenError
from app.core.database import AsyncSessionLocal, get_db
from app.core.graph_database import driver as graph_driver
from app.core.middleware import get_correlation_id, get_current_user_id
from app.models.document import (
    DocumentListItem,
    DocumentListResponse,
    DocumentStatus,
    DocumentStatusResponse,
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


async def _process_uploaded_document(
    document_id: uuid.UUID, filename: str, content: bytes, correlation_id: str
) -> None:
    """Run the ingestion pipeline, then link references, after the response is sent.

    Runs as a FastAPI background task — the request's own database and
    graph sessions are already torn down by the time this executes, so
    this opens brand new ones of its own rather than reusing them.

    correlation_id is passed in rather than read via get_correlation_id():
    that function reads a contextvar the middleware already resets back to
    empty by the time a background task runs, so calling it in here would
    silently log a blank ID instead of the real one from the request.
    """
    async with AsyncSessionLocal() as db:
        repository = DocumentRepository(db)
        service = IngestionService(repository, PermissionRepository(db))
        await service.process_document(document_id, filename, content)

        document = await repository.get_by_id(document_id)
        if document is not None and document.status == DocumentStatus.READY:
            try:
                text = extract_text(filename, content)
                async with graph_driver.session() as graph_session:
                    graph_service = DocumentGraphService(repository, GraphRepository(graph_session))
                    await graph_service.build_references(document, text)
            except CircuitOpenError:
                logger.error(
                    "Reference extraction unavailable, document uploaded without graph links",
                    extra={"correlation_id": correlation_id},
                )


@router.post("/upload", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """Accept one uploaded file, record it, and process it in the background."""
    if not file.filename or not file.filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise HTTPException(status_code=400, detail="Only .pdf and .txt files are supported")

    content = await file.read()
    user_id = get_current_user_id()
    correlation_id = get_correlation_id()

    service = IngestionService(DocumentRepository(db), PermissionRepository(db))
    document = await service.create_document(file.filename, user_id)

    await AuditRepository(db).log_action(
        correlation_id=correlation_id,
        action="document_upload",
        resource_type="document",
        resource_id=str(document.id),
        extra_data={"filename": document.filename, "status": document.status.value},
        user_id=user_id,
    )

    background_tasks.add_task(
        _process_uploaded_document, document.id, file.filename, content, correlation_id
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


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> DocumentStatusResponse:
    """Report one document's progress through the ingestion pipeline, for polling."""
    user_id = get_current_user_id()
    document = await DocumentRepository(db).get_document_for_user(document_id, user_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    return DocumentStatusResponse(
        id=document.id,
        status=document.status,
        processing_stage=document.processing_stage,
        pii_detected=document.pii_detected,
        failure_reason=document.failure_reason,
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
