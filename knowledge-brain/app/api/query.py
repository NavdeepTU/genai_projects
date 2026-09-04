from fastapi import APIRouter, Depends, HTTPException
from neo4j import AsyncSession as Neo4jAsyncSession
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.circuit_breaker import CircuitOpenError
from app.core.database import get_db
from app.core.graph_database import get_graph_session
from app.core.middleware import get_correlation_id, get_current_user_id
from app.models.query import QueryRequest, QueryResponse
from app.repositories.audit_repository import AuditRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.graph_repository import GraphRepository
from app.services.federated_retrieval_service import FederatedRetrievalService
from app.services.retrieval_service import RetrievalUnavailableError

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    db: AsyncSession = Depends(get_db),
    graph_session: Neo4jAsyncSession = Depends(get_graph_session),
) -> QueryResponse:
    """Answer a question using retrieval-augmented generation.

    Routes through FederatedRetrievalService, not RetrievalService
    directly, so a question needing more than one document domain (see
    ADR-040) is handled transparently — this route has no awareness of
    whether one domain answered or several did.
    """
    service = FederatedRetrievalService(DocumentRepository(db), GraphRepository(graph_session))
    user_id = get_current_user_id()

    try:
        result = await service.run_query(request.question, user_id)
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
    audit = AuditRepository(db)
    await audit.log_query_made(
        correlation_id=correlation_id,
        user_id=user_id,
        question=request.question,
        duration_ms=result.duration_ms,
    )
    if result.blocked:
        await audit.log_answer_blocked(
            correlation_id=correlation_id,
            user_id=user_id,
            question=request.question,
            block_reason=result.block_reason or "unknown",
        )

    return QueryResponse(
        answer=result.answer,
        sources=result.sources,
        confidence=result.confidence,
        correlation_id=correlation_id,
    )
