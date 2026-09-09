import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_auth import require_admin
from app.core.blob_storage import download_document
from app.core.circuit_breaker import CircuitOpenError
from app.core.database import AsyncSessionLocal, get_db
from app.core.graph_database import driver as graph_driver
from app.core.middleware import get_correlation_id, get_current_tenant_id, get_current_user_id
from app.models.admin import AdminAuditEntry, AdminResponse, ReviewQueueItem, ReviewQueueResponse
from app.models.document import DocumentStatus, DocumentStatusResponse
from app.models.domain import (
    CreateDomainRequest,
    DomainDetailResponse,
    DomainListResponse,
    DomainResponse,
    MergeDomainRequest,
    RenameDomainRequest,
)
from app.models.tenant import CreateTenantRequest, CreateTenantResponse
from app.repositories.audit_repository import AuditRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.domain_repository import DomainRepository
from app.repositories.graph_repository import GraphRepository
from app.repositories.tenant_repository import TenantRepository
from app.services.document_graph_service import DocumentGraphService
from app.services.extraction import extract_text
from app.services.ingestion_service import IngestionService

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("", response_model=AdminResponse)
async def get_admin(db: AsyncSession = Depends(get_db)) -> AdminResponse:
    """Return the admin digest: recent activity across every user and tenant."""
    correlation_id = get_correlation_id()

    audit_entries = await AuditRepository(db).get_all_recent_entries(correlation_id=correlation_id)

    return AdminResponse(
        audit_entries=[
            AdminAuditEntry(
                timestamp=entry.timestamp,
                tenant_id=entry.tenant_id,
                user_id=entry.user_id,
                action=entry.action,
                resource_type=entry.resource_type,
                resource_id=entry.resource_id,
            )
            for entry in audit_entries
        ],
        correlation_id=correlation_id,
    )


@router.post("/tenants", response_model=CreateTenantResponse, status_code=201)
async def create_tenant(body: CreateTenantRequest, db: AsyncSession = Depends(get_db)) -> CreateTenantResponse:
    """Register a new tenant — the only way one can ever be created (ADR-046).

    A user never creates their own tenant; they only ever pick one that
    already exists (GET /tenants) at signup. Gated by require_admin at
    the router level, same as every other route here.
    """
    correlation_id = get_correlation_id()
    tenant_repository = TenantRepository(db)

    existing = await tenant_repository.get_tenant_by_name(body.name)
    if existing is not None:
        raise HTTPException(status_code=409, detail="A tenant with this name already exists")

    # The check above is only a friendlier common case — it can't stop two
    # concurrent requests for the same name from both passing it. The
    # unique constraint on tenants.name is the real guarantee; this catches
    # its violation and reports the same 409 rather than an unhandled 500.
    try:
        tenant = await tenant_repository.create_tenant(body.name)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="A tenant with this name already exists") from None

    await AuditRepository(db).log_action(
        correlation_id=correlation_id,
        action="tenant_registered",
        resource_type="tenant",
        resource_id=str(tenant.id),
        extra_data={"name": tenant.name},
        user_id=get_current_user_id(),
    )

    return CreateTenantResponse(id=tenant.id, name=tenant.name, correlation_id=correlation_id)


async def _approve_and_process_in_background(document_id: uuid.UUID, correlation_id: str) -> None:
    """Re-run ingestion for an approved document, then link its references (ADR-048).

    Mirrors app/api/documents.py's own _process_uploaded_document: a
    FastAPI background task needs its own fresh database and Neo4j
    sessions, since the request's are already torn down by the time
    this actually runs.
    """
    async with AsyncSessionLocal() as db:
        repository = DocumentRepository(db)
        service = IngestionService(repository)
        await service.approve_and_process(document_id)

        document = await repository.get_by_id(document_id)
        if document is not None and document.status == DocumentStatus.READY:
            try:
                content = await download_document(document.storage_path)
                text = extract_text(document.filename, content)
                async with graph_driver.session() as graph_session:
                    graph_service = DocumentGraphService(repository, GraphRepository(graph_session))
                    await graph_service.build_references(document, text)
            except CircuitOpenError:
                pass


@router.get("/review-queue", response_model=ReviewQueueResponse)
async def get_review_queue(db: AsyncSession = Depends(get_db)) -> ReviewQueueResponse:
    """Return every document awaiting a PII-review decision in this admin's own tenant (ADR-048).

    Scoped to the admin's own tenant, not global — reviewing another
    tenant's flagged PII content would be exactly the cross-tenant leak
    ADR-046 closed elsewhere in this system, reopened here if this
    weren't tenant-scoped too.
    """
    tenant_id = uuid.UUID(get_current_tenant_id())
    rows = await DocumentRepository(db).list_review_queue_for_tenant(tenant_id)

    return ReviewQueueResponse(
        documents=[
            ReviewQueueItem(
                id=doc.id,
                filename=doc.filename,
                uploaded_at=doc.uploaded_at,
                uploaded_by_email=email,
                has_file=doc.has_file,
            )
            for doc, email in rows
        ],
        correlation_id=get_correlation_id(),
    )


@router.post("/documents/{document_id}/approve", response_model=DocumentStatusResponse)
async def approve_document(
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> DocumentStatusResponse:
    """Approve a document held for PII review — an audited human override (ADR-048).

    Re-running the pipeline (chunking, embedding) happens in the
    background, the same "return immediately, finish later" shape every
    other document-processing step in this project already uses — this
    can take as long as a fresh upload does, since it effectively is
    one. Approving embeds the document's real text, PII included: a
    deliberate, explicit exception to this project's own "never embed
    raw PII" rule (CLAUDE.md Requirement 4), made once, by a specific
    admin, on one specific document — not a blanket policy change.
    """
    tenant_id = uuid.UUID(get_current_tenant_id())
    document = await DocumentRepository(db).get_document_for_tenant(document_id, tenant_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.status != DocumentStatus.IN_REVIEW:
        raise HTTPException(status_code=400, detail="Document is not pending review")

    correlation_id = get_correlation_id()
    await AuditRepository(db).log_action(
        correlation_id=correlation_id,
        action="document_approved",
        resource_type="document",
        resource_id=str(document_id),
        extra_data={"filename": document.filename},
        tenant_id=str(tenant_id),
        user_id=get_current_user_id(),
    )

    background_tasks.add_task(_approve_and_process_in_background, document_id, correlation_id)

    return DocumentStatusResponse(
        id=document.id,
        status=DocumentStatus.PROCESSING,
        processing_stage=document.processing_stage,
        pii_detected=document.pii_detected,
        failure_reason=document.failure_reason,
        correlation_id=correlation_id,
    )


@router.post("/documents/{document_id}/reject", response_model=DocumentStatusResponse)
async def reject_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> DocumentStatusResponse:
    """Reject a document held for PII review — terminal, no resubmission possible (ADR-048)."""
    tenant_id = uuid.UUID(get_current_tenant_id())
    document = await DocumentRepository(db).get_document_for_tenant(document_id, tenant_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.status != DocumentStatus.IN_REVIEW:
        raise HTTPException(status_code=400, detail="Document is not pending review")

    await DocumentRepository(db).reject_document(document_id)

    await AuditRepository(db).log_action(
        correlation_id=get_correlation_id(),
        action="document_rejected",
        resource_type="document",
        resource_id=str(document_id),
        extra_data={"filename": document.filename},
        tenant_id=str(tenant_id),
        user_id=get_current_user_id(),
    )

    return DocumentStatusResponse(
        id=document.id,
        status=DocumentStatus.REJECTED,
        processing_stage=document.processing_stage,
        pii_detected=document.pii_detected,
        failure_reason=document.failure_reason,
        correlation_id=get_correlation_id(),
    )


@router.post("/domains", response_model=DomainDetailResponse, status_code=201)
async def create_domain(body: CreateDomainRequest, db: AsyncSession = Depends(get_db)) -> DomainDetailResponse:
    """Register a new domain for the admin's own tenant — the only way one can be created.

    This is the actual fix for domain vocabulary drift: a domain can no
    longer be typed freely at upload (ADR-040's original design), only
    created here, deliberately, by an admin.
    """
    correlation_id = get_correlation_id()
    tenant_id = uuid.UUID(get_current_tenant_id())
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Domain name cannot be empty")

    repository = DomainRepository(db)
    existing = await repository.get_by_name_for_tenant(tenant_id, name)
    if existing is not None:
        raise HTTPException(status_code=409, detail="A domain with this name already exists")

    try:
        domain = await repository.create_domain(tenant_id, name)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="A domain with this name already exists") from None

    await AuditRepository(db).log_action(
        correlation_id=correlation_id,
        action="domain_created",
        resource_type="domain",
        resource_id=str(domain.id),
        extra_data={"name": domain.name},
        tenant_id=str(tenant_id),
        user_id=get_current_user_id(),
    )

    return DomainDetailResponse(id=domain.id, name=domain.name, correlation_id=correlation_id)


@router.patch("/domains/{domain_id}", response_model=DomainDetailResponse)
async def rename_domain(
    domain_id: uuid.UUID, body: RenameDomainRequest, db: AsyncSession = Depends(get_db)
) -> DomainDetailResponse:
    """Rename a domain — fixes drift already noticed ("Human Resources" → "HR")
    in one action, since every document already tagged with it keeps pointing
    at the same domain_id."""
    correlation_id = get_correlation_id()
    tenant_id = uuid.UUID(get_current_tenant_id())
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Domain name cannot be empty")

    repository = DomainRepository(db)
    domain = await repository.get_by_id_for_tenant(domain_id, tenant_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")

    existing = await repository.get_by_name_for_tenant(tenant_id, name)
    if existing is not None and existing.id != domain_id:
        raise HTTPException(status_code=409, detail="A domain with this name already exists")

    try:
        await repository.rename_domain(domain_id, name)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="A domain with this name already exists") from None

    await AuditRepository(db).log_action(
        correlation_id=correlation_id,
        action="domain_renamed",
        resource_type="domain",
        resource_id=str(domain_id),
        extra_data={"old_name": domain.name, "new_name": name},
        tenant_id=str(tenant_id),
        user_id=get_current_user_id(),
    )

    domain.name = name
    return DomainDetailResponse(id=domain.id, name=domain.name, correlation_id=correlation_id)


@router.post("/domains/{domain_id}/merge", response_model=DomainListResponse)
async def merge_domain(
    domain_id: uuid.UUID, body: MergeDomainRequest, db: AsyncSession = Depends(get_db)
) -> DomainListResponse:
    """Merge one domain into another — every document tagged with domain_id
    ends up tagged with target_id instead, and domain_id is deleted.

    The real fix for drift that's already happened: "HR" and "Human
    Resources" both existing as separate domains gets collapsed to one,
    in a single action, instead of hunting down every document that used
    the old spelling.
    """
    tenant_id = uuid.UUID(get_current_tenant_id())
    if domain_id == body.target_id:
        raise HTTPException(status_code=400, detail="Cannot merge a domain into itself")

    repository = DomainRepository(db)
    source = await repository.get_by_id_for_tenant(domain_id, tenant_id)
    target = await repository.get_by_id_for_tenant(body.target_id, tenant_id)
    if source is None or target is None:
        raise HTTPException(status_code=404, detail="Domain not found")

    await repository.merge_domain(domain_id, body.target_id)

    await AuditRepository(db).log_action(
        correlation_id=get_correlation_id(),
        action="domain_merged",
        resource_type="domain",
        resource_id=str(body.target_id),
        extra_data={"merged_name": source.name, "into_name": target.name},
        tenant_id=str(tenant_id),
        user_id=get_current_user_id(),
    )

    remaining = await repository.list_for_tenant(tenant_id)
    return DomainListResponse(
        domains=[DomainResponse.model_validate(d) for d in remaining],
        correlation_id=get_correlation_id(),
    )


@router.delete("/domains/{domain_id}", status_code=204)
async def delete_domain(domain_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Response:
    """Delete a domain entirely — any document tagged with it is simply untagged."""
    tenant_id = uuid.UUID(get_current_tenant_id())
    repository = DomainRepository(db)
    domain = await repository.get_by_id_for_tenant(domain_id, tenant_id)
    if domain is None:
        raise HTTPException(status_code=404, detail="Domain not found")

    await repository.delete_domain(domain_id)

    await AuditRepository(db).log_action(
        correlation_id=get_correlation_id(),
        action="domain_deleted",
        resource_type="domain",
        resource_id=str(domain_id),
        extra_data={"name": domain.name},
        tenant_id=str(tenant_id),
        user_id=get_current_user_id(),
    )

    return Response(status_code=204)
