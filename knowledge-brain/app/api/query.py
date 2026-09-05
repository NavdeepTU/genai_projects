from fastapi import APIRouter, Depends, HTTPException
from neo4j import AsyncSession as Neo4jAsyncSession
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.circuit_breaker import CircuitOpenError
from app.core.database import get_db
from app.core.graph_database import get_graph_session
from app.core.middleware import get_correlation_id, get_current_user_id
from app.models.conversation import TITLE_MAX_LENGTH, Conversation
from app.models.query import QueryRequest, QueryResponse
from app.repositories.audit_repository import AuditRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.graph_repository import GraphRepository
from app.services.federated_retrieval_service import FederatedRetrievalService
from app.services.retrieval_service import RetrievalUnavailableError

router = APIRouter(prefix="/query", tags=["query"])


def _conversation_title(question: str) -> str:
    """Turn a first question into a short sidebar label — no LLM call, just a truncation."""
    question = question.strip()
    if len(question) <= TITLE_MAX_LENGTH:
        return question
    return question[: TITLE_MAX_LENGTH - 1].rstrip() + "…"


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
    whether one domain answered or several did. Every call now also
    belongs to a conversation (ADR-041): an existing one if
    conversation_id was given (checked against this user before anything
    else runs, so a bad id fails fast rather than after paying for
    retrieval), or a new one created only once the answer actually comes
    back — a failed attempt (a 503 below) never leaves an empty
    conversation sitting in the sidebar.
    """
    user_id = get_current_user_id()
    conversation_repo = ConversationRepository(db)

    conversation: Conversation | None = None
    if request.conversation_id is not None:
        conversation = await conversation_repo.get_conversation_for_user(
            request.conversation_id, user_id
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

    service = FederatedRetrievalService(DocumentRepository(db), GraphRepository(graph_session))

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

    if conversation is None:
        conversation = await conversation_repo.create_conversation(
            user_id, title=_conversation_title(request.question)
        )

    await conversation_repo.add_turn(
        conversation.id,
        raw_question=request.question,
        # Condensing (build-order item 18's other half) isn't built yet —
        # stored equal to the raw question as a placeholder until it is.
        condensed_question=request.question,
        answer=result.answer,
        sources=[source.model_dump(mode="json") for source in result.sources],
        confidence=result.confidence,
        domains_used=result.domains_used,
        correlation_id=correlation_id,
    )

    return QueryResponse(
        answer=result.answer,
        sources=result.sources,
        confidence=result.confidence,
        conversation_id=conversation.id,
        correlation_id=correlation_id,
    )
