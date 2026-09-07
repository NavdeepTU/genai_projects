import logging
import uuid
from pathlib import Path

from azure.core.exceptions import AzureError
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from fastapi.responses import Response
from neo4j import AsyncSession as Neo4jAsyncSession
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.blob_storage import download_document
from app.core.circuit_breaker import CircuitOpenError
from app.core.database import AsyncSessionLocal, get_db
from app.core.graph_database import driver as graph_driver
from app.core.graph_database import get_graph_session
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
from app.services.document_deletion_service import DocumentDeletionService
from app.services.document_graph_service import DocumentGraphService
from app.services.extraction import extract_text
from app.services.ingestion_service import CONTENT_TYPES, IngestionService

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
    domains: str = Form(""),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """Accept one uploaded file, record it, and process it in the background.

    domains is a comma-separated string, not a real list — multipart form
    fields don't carry structured types the way a JSON body would. Set
    manually at upload, for now (see ADR-040); empty means untagged, same
    as before this feature existed.
    """
    if not file.filename or not file.filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise HTTPException(status_code=400, detail="Only .pdf and .txt files are supported")

    domain_list = [d.strip() for d in domains.split(",") if d.strip()]
    content = await file.read()
    user_id = get_current_user_id()
    correlation_id = get_correlation_id()

    service = IngestionService(DocumentRepository(db), PermissionRepository(db))
    document = await service.create_document(file.filename, content, user_id, domain_list)

    await AuditRepository(db).log_action(
        correlation_id=correlation_id,
        action="document_upload",
        resource_type="document",
        resource_id=str(document.id),
        extra_data={"filename": document.filename, "status": document.status.value, "domains": domain_list},
        user_id=user_id,
    )

    background_tasks.add_task(
        _process_uploaded_document, document.id, file.filename, content, correlation_id
    )

    return DocumentUploadResponse(
        id=document.id,
        filename=document.filename,
        status=document.status,
        domains=document.domains,
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


@router.get("/{document_id}/content")
async def get_document_content(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Serve a document's original file, so it can be opened in the browser (ADR-044).

    Permission-checked exactly like every other document access in this
    system — get_document_for_user returns None for a document this user
    was never granted access to, the same as a nonexistent id. A document
    with no storage_path (uploaded before this feature existed, or whose
    blob save itself failed) has nothing to serve, a 404 same as a
    missing document rather than a different error shape to handle.
    Content-Disposition: inline is what makes the browser render a PDF or
    text file directly instead of downloading it.
    """
    user_id = get_current_user_id()
    document = await DocumentRepository(db).get_document_for_user(document_id, user_id)
    if document is None or document.storage_path is None:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        content = await download_document(document.storage_path)
    except (CircuitOpenError, AzureError):
        raise HTTPException(
            status_code=503,
            detail="Document storage is temporarily unavailable. Please try again in a moment.",
        ) from None

    content_type = CONTENT_TYPES.get(Path(document.filename).suffix.lower(), "application/octet-stream")
    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{document.filename}"'},
    )


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    graph_session: Neo4jAsyncSession = Depends(get_graph_session),
) -> Response:
    """Delete a document completely — its file, its graph node, and its database rows (ADR-045).

    Permission-checked exactly like viewing or listing: anyone with
    access to a document can delete it today, the same has_access rule
    grant_document_access already uses — there's no separate "owner"
    concept in this project's permission model yet.
    """
    user_id = get_current_user_id()
    document = await DocumentRepository(db).get_document_for_user(document_id, user_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    filename = document.filename
    service = DocumentDeletionService(DocumentRepository(db), GraphRepository(graph_session))
    try:
        await service.delete_document(document)
    except SQLAlchemyError:
        raise HTTPException(
            status_code=503,
            detail="Couldn't delete the document. Please try again in a moment.",
        ) from None

    await AuditRepository(db).log_action(
        correlation_id=get_correlation_id(),
        action="document_deleted",
        resource_type="document",
        resource_id=str(document_id),
        extra_data={"filename": filename},
        user_id=user_id,
    )

    return Response(status_code=204)


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
