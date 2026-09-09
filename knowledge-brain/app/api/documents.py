import logging
import uuid
from pathlib import Path

from azure.core.exceptions import AzureError
from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from fastapi.responses import Response
from neo4j import AsyncSession as Neo4jAsyncSession
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_auth import is_admin_user
from app.core.blob_storage import download_document
from app.core.circuit_breaker import CircuitOpenError
from app.core.database import AsyncSessionLocal, get_db
from app.core.graph_database import driver as graph_driver
from app.core.graph_database import get_graph_session
from app.core.middleware import get_correlation_id, get_current_tenant_id, get_current_user_id
from app.models.document import (
    DocumentListItem,
    DocumentListResponse,
    DocumentStatus,
    DocumentStatusResponse,
    DocumentUploadResponse,
)
from app.repositories.audit_repository import AuditRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.graph_repository import GraphRepository
from app.services.document_deletion_service import DocumentDeletionService
from app.services.document_graph_service import DocumentGraphService
from app.services.extraction import extract_text
from app.services.ingestion_service import CONTENT_TYPES, IngestionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_EXTENSIONS = (".pdf", ".txt")

# A document held anywhere in the PII review workflow (ADR-048) is the
# one exception to plain tenant-wide visibility — visible only to its
# own uploader, or an admin, not the rest of the tenant.
_REVIEW_STATUSES = (DocumentStatus.PENDING_REVIEW, DocumentStatus.IN_REVIEW, DocumentStatus.REJECTED)


async def _visible_to_caller(document, db: AsyncSession) -> bool:
    """Whether the current caller may view one specific document's status/content.

    Every non-review-held document is visible tenant-wide already
    (get_document_for_tenant's own filter) — this only narrows further
    for the three review statuses, where a plain tenant member who isn't
    the uploader or an admin gets treated as if the document doesn't
    exist, the same indistinguishable-404 shape this project already
    uses for a document in a different tenant entirely.
    """
    if document.status not in _REVIEW_STATUSES:
        return True
    if document.uploaded_by is not None and str(document.uploaded_by) == get_current_user_id():
        return True
    return await is_admin_user(db)


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
        service = IngestionService(repository)
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
    domain_ids: str = Form(""),
    db: AsyncSession = Depends(get_db),
) -> DocumentUploadResponse:
    """Accept one uploaded file, record it, and process it in the background.

    domain_ids is a comma-separated string of domain UUIDs, not a real
    list — multipart form fields don't carry structured types the way a
    JSON body would. Picked from GET /domains's real, admin-managed list
    (see app/models/domain.py) rather than typed freely; an entry that
    doesn't parse as a UUID is silently skipped, and IngestionService
    drops anything that doesn't belong to this tenant. Empty means
    untagged, same as before this feature existed.
    """
    if not file.filename or not file.filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise HTTPException(status_code=400, detail="Only .pdf and .txt files are supported")

    parsed_domain_ids: list[uuid.UUID] = []
    for raw_id in domain_ids.split(","):
        raw_id = raw_id.strip()
        if not raw_id:
            continue
        try:
            parsed_domain_ids.append(uuid.UUID(raw_id))
        except ValueError:
            continue

    content = await file.read()
    user_id = get_current_user_id()
    tenant_id = uuid.UUID(get_current_tenant_id())
    correlation_id = get_correlation_id()

    service = IngestionService(DocumentRepository(db))
    document = await service.create_document(
        file.filename, content, tenant_id, uuid.UUID(user_id), parsed_domain_ids
    )

    await AuditRepository(db).log_action(
        correlation_id=correlation_id,
        action="document_upload",
        resource_type="document",
        resource_id=str(document.id),
        extra_data={"filename": document.filename, "status": document.status.value, "domains": document.domains},
        tenant_id=str(tenant_id),
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
    """Return every document the calling user's tenant can see, newest first (ADR-046).

    A document held for PII review (ADR-048) is the one exception —
    only its own uploader sees it here until an admin approves it.
    """
    tenant_id = uuid.UUID(get_current_tenant_id())
    caller_id = uuid.UUID(get_current_user_id())
    documents = await DocumentRepository(db).list_documents_for_tenant(tenant_id, caller_id)
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
    tenant_id = uuid.UUID(get_current_tenant_id())
    document = await DocumentRepository(db).get_document_for_tenant(document_id, tenant_id)
    if document is None or not await _visible_to_caller(document, db):
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

    Tenant-checked exactly like every other document access in this
    system (ADR-046) — get_document_for_tenant returns None for a
    document belonging to another tenant, the same as a nonexistent id.
    A document with no storage_path (uploaded before this feature
    existed, or whose blob save itself failed) has nothing to serve, a
    404 same as a missing document rather than a different error shape
    to handle. Content-Disposition: inline is what makes the browser
    render a PDF or text file directly instead of downloading it.
    """
    tenant_id = uuid.UUID(get_current_tenant_id())
    document = await DocumentRepository(db).get_document_for_tenant(document_id, tenant_id)
    if document is None or document.storage_path is None or not await _visible_to_caller(document, db):
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


@router.post("/{document_id}/submit-review", response_model=DocumentStatusResponse)
async def submit_document_for_review(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> DocumentStatusResponse:
    """Move a held document into the admin review queue (ADR-048).

    Only the document's own uploader can do this — or an admin, for a
    legacy document with no recorded uploader at all, so an orphaned
    flagged document isn't permanently stuck with no one able to act on
    it. Anyone else gets the same 404 shape this project already uses
    for a document they have no business knowing exists.
    """
    tenant_id = uuid.UUID(get_current_tenant_id())
    document = await DocumentRepository(db).get_document_for_tenant(document_id, tenant_id)
    if document is None or not await _visible_to_caller(document, db):
        raise HTTPException(status_code=404, detail="Document not found")
    if document.status != DocumentStatus.PENDING_REVIEW:
        raise HTTPException(status_code=400, detail="Document is not awaiting review submission")

    await DocumentRepository(db).submit_for_review(document_id)

    await AuditRepository(db).log_action(
        correlation_id=get_correlation_id(),
        action="document_submitted_for_review",
        resource_type="document",
        resource_id=str(document_id),
        extra_data={"filename": document.filename},
        tenant_id=str(tenant_id),
        user_id=get_current_user_id(),
    )

    return DocumentStatusResponse(
        id=document.id,
        status=DocumentStatus.IN_REVIEW,
        processing_stage=document.processing_stage,
        pii_detected=document.pii_detected,
        failure_reason=document.failure_reason,
        correlation_id=get_correlation_id(),
    )


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    graph_session: Neo4jAsyncSession = Depends(get_graph_session),
) -> Response:
    """Delete a document completely — its file, its graph node, and its database rows (ADR-045).

    Tenant-checked exactly like viewing or listing (ADR-046): anyone in
    the same tenant as a document can delete it today, the same
    tenant-membership rule that already governs seeing it — there's no
    separate "owner" concept in this project's permission model.
    """
    tenant_id = uuid.UUID(get_current_tenant_id())
    document = await DocumentRepository(db).get_document_for_tenant(document_id, tenant_id)
    if document is None or not await _visible_to_caller(document, db):
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
        tenant_id=str(tenant_id),
        user_id=get_current_user_id(),
    )

    return Response(status_code=204)
