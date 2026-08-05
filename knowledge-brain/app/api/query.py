from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.circuit_breaker import CircuitOpenError
from app.core.database import get_db
from app.core.middleware import get_correlation_id
from app.models.query import QueryRequest, QueryResponse
from app.repositories.audit_repository import AuditRepository
from app.repositories.document_repository import DocumentRepository
from app.services.retrieval_service import RetrievalService, RetrievalUnavailableError

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    """Answer a question using retrieval-augmented generation."""
    service = RetrievalService(DocumentRepository(db))

    try:
        answer = await service.answer_question(request.question)
    except CircuitOpenError:
        raise HTTPException(
            status_code=503,
            detail="The query engine is temporarily unavailable. Please try again in a moment.",
        ) from None
    except RetrievalUnavailableError:
        raise HTTPException(
            status_code=503,
            detail="Search is temporarily unavailable. Please try again in a moment.",
        ) from None

    correlation_id = get_correlation_id()
    await AuditRepository(db).log_action(
        correlation_id=correlation_id,
        action="query_made",
        resource_type="query",
        resource_id=correlation_id,
        extra_data={"question": request.question},
    )

    return QueryResponse(answer=answer, correlation_id=correlation_id)
