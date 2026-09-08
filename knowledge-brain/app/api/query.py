import uuid

from fastapi import APIRouter, Depends, HTTPException
from neo4j import AsyncSession as Neo4jAsyncSession
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.circuit_breaker import CircuitOpenError
from app.core.database import get_db
from app.core.graph_database import get_graph_session
from app.core.middleware import get_correlation_id, get_current_tenant_id, get_current_user_id
from app.models.conversation import TITLE_MAX_LENGTH, Conversation, RecentTurn
from app.models.query import QueryRequest, QueryResponse
from app.repositories.audit_repository import AuditRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.graph_repository import GraphRepository
from app.services.condensing import get_effective_question, update_recent_turns_cache
from app.services.federated_retrieval_service import FederatedRetrievalService
from app.services.retrieval_service import RetrievalUnavailableError

router = APIRouter(prefix="/query", tags=["query"])


def _conversation_title(question: str) -> str:
    """Turn a first question into a short sidebar label — no LLM call, just a truncation."""
    question = question.strip()
    if len(question) <= TITLE_MAX_LENGTH:
        return question
    return question[: TITLE_MAX_LENGTH - 1].rstrip() + "…"


async def resolve_conversation(
    conversation_repo: ConversationRepository, conversation_id: uuid.UUID | None, user_id: str
) -> Conversation | None:
    """Look up a named conversation, or None to start a new one — shared by /query and
    /query/stream so both fail the same way on a bad id, before either pays for retrieval.
    """
    if conversation_id is None:
        return None
    conversation = await conversation_repo.get_conversation_for_user(conversation_id, user_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


async def save_turn_and_refresh_cache(
    conversation_repo: ConversationRepository,
    conversation: Conversation | None,
    *,
    user_id: str,
    raw_question: str,
    condensed_question: str,
    answer: str,
    sources: list[dict],
    confidence: float | None,
    domains_used: list[str],
    correlation_id: str,
    recent_turns: list[RecentTurn],
) -> Conversation:
    """Create the conversation if this was its first turn, save the turn, and refresh the
    condensing cache — shared by /query and /query/stream so a turn is recorded identically
    regardless of how the answer was delivered.
    """
    if conversation is None:
        conversation = await conversation_repo.create_conversation(
            user_id, title=_conversation_title(raw_question)
        )

    await conversation_repo.add_turn(
        conversation.id,
        raw_question=raw_question,
        condensed_question=condensed_question,
        answer=answer,
        sources=sources,
        confidence=confidence,
        domains_used=domains_used,
        correlation_id=correlation_id,
    )

    await update_recent_turns_cache(conversation.id, recent_turns, condensed_question, answer)
    return conversation


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

    A follow-up in an existing conversation is condensed into a
    standalone question before it ever reaches the pipeline (ADR-042):
    the condensed text is what's actually retrieved and answered
    against, not the raw one — the input guardrail inside
    FederatedRetrievalService runs on this condensed text, since that's
    what actually enters the pipeline. A brand-new conversation has no
    prior turns to condense against, so its first question always
    passes through unchanged.

    This is still the one entry point every non-browser caller (MCP, the
    evaluation harness) uses — the streaming endpoint (`/query/stream`,
    ADR-043) is a genuinely separate route with its own delivery
    mechanism, not a replacement for this one.
    """
    user_id = get_current_user_id()
    tenant_id = get_current_tenant_id()
    conversation_repo = ConversationRepository(db)

    conversation = await resolve_conversation(conversation_repo, request.conversation_id, user_id)
    condensed_question, recent_turns = await get_effective_question(request.question, conversation)

    service = FederatedRetrievalService(DocumentRepository(db), GraphRepository(graph_session))

    try:
        result = await service.run_query(condensed_question, user_id, tenant_id)
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
        tenant_id=tenant_id,
        user_id=user_id,
        question=request.question,
        duration_ms=result.duration_ms,
    )
    if result.blocked:
        await audit.log_answer_blocked(
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            user_id=user_id,
            question=request.question,
            block_reason=result.block_reason or "unknown",
        )

    conversation = await save_turn_and_refresh_cache(
        conversation_repo,
        conversation,
        user_id=user_id,
        raw_question=request.question,
        condensed_question=condensed_question,
        answer=result.answer,
        sources=[source.model_dump(mode="json") for source in result.sources],
        confidence=result.confidence,
        domains_used=result.domains_used,
        correlation_id=correlation_id,
        recent_turns=recent_turns,
    )

    return QueryResponse(
        answer=result.answer,
        sources=result.sources,
        confidence=result.confidence,
        conversation_id=conversation.id,
        correlation_id=correlation_id,
    )
