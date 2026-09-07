import logging
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from neo4j import AsyncSession as Neo4jAsyncSession
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.query import resolve_conversation, save_turn_and_refresh_cache
from app.core.circuit_breaker import CircuitOpenError
from app.core.database import get_db
from app.core.graph_database import get_graph_session
from app.core.middleware import get_correlation_id, get_current_user_id
from app.models.query import (
    QueryRequest,
    QuerySource,
    StreamChunkEvent,
    StreamDoneEvent,
    StreamErrorEvent,
    StreamRetractEvent,
    StreamTtftEvent,
)
from app.repositories.audit_repository import AuditRepository
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.graph_repository import GraphRepository
from app.services.condensing import get_effective_question
from app.services.federated_retrieval_service import (
    FederatedRetrievalService,
    MultiPrepared,
    SinglePrepared,
)
from app.services.retrieval_service import BLOCKED_MESSAGE, RetrievalUnavailableError
from app.services.streaming import StreamChunk, StreamDone, StreamRetract, stream_checked_answer

router = APIRouter(prefix="/query", tags=["query"])

logger = logging.getLogger(__name__)


def _sse(event: str, data: BaseModel) -> str:
    """Format one Server-Sent Event frame — `event: <type>\\ndata: <json>\\n\\n`.

    Takes a Pydantic model, not a raw dict, so every event's shape is
    type-checked the same way QueryResponse already is — the frontend's
    StreamEvent union is meant to match these models field for field.
    """
    return f"event: {event}\ndata: {data.model_dump_json()}\n\n"


@router.post("/stream")
async def query_stream(
    request: QueryRequest,
    db: AsyncSession = Depends(get_db),
    graph_session: Neo4jAsyncSession = Depends(get_graph_session),
) -> StreamingResponse:
    """Answer a question the same way /query does, but deliver it as it's generated (ADR-043).

    Conversation resolution, condensing, retrieval, reranking, ACL
    filtering, and the multi-agent federated retrieval path (ADR-040) all
    run exactly as they do for /query, and all complete before this
    response is ever created — only the final generation step streams
    (requirement 11). A bad conversation_id or an unavailable retrieval
    dependency still fails as a normal HTTP error here, before any bytes
    are sent, for the same reason /query does.

    A single-domain question streams for real: each sentence is
    moderation-checked as it's produced and released as a `chunk` event,
    time-to-first-token is reported once as a `ttft` event, and if the
    complete answer fails the injection check afterward, a `retract`
    event tells the client to erase what it already showed. A
    multi-domain question has no per-domain-drafts-merged text to stream
    token by token — its synthesized answer arrives as one `chunk` event
    instead (a deliberate, named scope simplification: real streaming
    only applies to the common, single-domain case). Every path ends
    with one `done` event carrying the final answer, sources, whether it
    was blocked, and the conversation id — the one thing every caller
    needs regardless of how the answer got to them.
    """
    user_id = get_current_user_id()
    # `start` covers the whole request — it's what time-to-first-token is
    # measured against, since that's genuinely how long the user waits.
    # `pipeline_start` begins right before retrieval, matching where
    # /query's own FederatedRetrievalService.run_query starts its clock —
    # the audit log's duration_ms must mean the same thing on both
    # endpoints, or any dashboard averaging it across the two is skewed.
    start = time.monotonic()
    conversation_repo = ConversationRepository(db)

    conversation = await resolve_conversation(conversation_repo, request.conversation_id, user_id)
    condensed_question, recent_turns = await get_effective_question(request.question, conversation)

    service = FederatedRetrievalService(DocumentRepository(db), GraphRepository(graph_session))

    pipeline_start = time.monotonic()
    try:
        prepared = await service.prepare_for_generation(condensed_question, user_id)
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

    async def event_stream() -> AsyncIterator[str]:
        """Yield SSE frames for one query, then persist the turn once the answer is final.

        Streams real per-sentence chunks for a single-domain question
        (with a `ttft` event on the first one and a `retract` if a safety
        check flags something already shown), or sends the multi-domain
        synthesized answer as one `chunk`. Every path converges on
        writing the audit log and saving the turn, then emits exactly one
        `done` event — the one thing every caller needs, regardless of
        which branch produced the answer.
        """
        answer: str
        blocked: bool
        block_reason: str | None
        sources: list[QuerySource]
        confidence: float | None
        domains_used: list[str]
        partial = False

        if isinstance(prepared, SinglePrepared):
            state = prepared.state
            domains_used = [state["domain"]] if state["domain"] else []

            if state["blocked"]:
                answer, blocked, block_reason = state["answer"], True, state["block_reason"]
                sources, confidence = [], None
            else:
                context_chunks = [chunk.text for chunk in state["reranked_chunks"]] + state["graph_context"]
                answer, blocked, block_reason = "", False, None
                first_chunk_sent = False

                async for event in stream_checked_answer(state["original_question"], context_chunks):
                    if isinstance(event, StreamChunk):
                        if not first_chunk_sent:
                            first_chunk_sent = True
                            yield _sse("ttft", StreamTtftEvent(ms=(time.monotonic() - start) * 1000))
                        answer += event.text
                        yield _sse("chunk", StreamChunkEvent(text=event.text))
                    elif isinstance(event, StreamRetract):
                        blocked, block_reason, answer = True, event.reason, BLOCKED_MESSAGE
                        yield _sse("retract", StreamRetractEvent(reason=event.reason))
                    elif isinstance(event, StreamDone):
                        answer = event.full_text

                sources, confidence = (
                    ([], None) if blocked else await service.build_sources_and_confidence(state)
                )
        else:
            assert isinstance(prepared, MultiPrepared)
            domains_used = prepared.domains
            try:
                result = await service.synthesize_and_finalize(
                    condensed_question, prepared.succeeded, prepared.answerable, prepared.partial, prepared.domains
                )
            except RetrievalUnavailableError:
                logger.error(
                    "Synthesis unavailable mid-stream, blocking rather than guessing",
                    extra={"correlation_id": correlation_id},
                )
                answer, blocked, block_reason = BLOCKED_MESSAGE, True, "synthesis_unavailable"
                sources, confidence = [], None
            else:
                # Honor synthesize_and_finalize's own contract (it leaves
                # duration_ms at 0.0 for its caller to fill in) even
                # though nothing reads this particular FederatedResult
                # again — matching what _run_federated does for /query.
                result.duration_ms = (time.monotonic() - pipeline_start) * 1000
                answer, blocked, block_reason = result.answer, result.blocked, result.block_reason
                sources, confidence, partial = result.sources, result.confidence, result.partial
                domains_used = result.domains_used
                if not blocked:
                    # No per-domain-merged text exists to stream token by token — the
                    # synthesized answer arrives as one piece (see docstring above).
                    yield _sse("chunk", StreamChunkEvent(text=answer))

        duration_ms = (time.monotonic() - pipeline_start) * 1000

        try:
            audit = AuditRepository(db)
            await audit.log_query_made(
                correlation_id=correlation_id, user_id=user_id, question=request.question, duration_ms=duration_ms
            )
            if blocked:
                await audit.log_answer_blocked(
                    correlation_id=correlation_id,
                    user_id=user_id,
                    question=request.question,
                    block_reason=block_reason or "unknown",
                )
        except SQLAlchemyError:
            logger.error(
                "Failed to write audit log for streamed query", extra={"correlation_id": correlation_id}
            )
            yield _sse("error", StreamErrorEvent(detail="The answer was generated but couldn't be recorded."))
            return

        try:
            saved_conversation = await save_turn_and_refresh_cache(
                conversation_repo,
                conversation,
                user_id=user_id,
                raw_question=request.question,
                condensed_question=condensed_question,
                answer=answer,
                sources=[source.model_dump(mode="json") for source in sources],
                confidence=confidence,
                domains_used=domains_used,
                correlation_id=correlation_id,
                recent_turns=recent_turns,
            )
        except SQLAlchemyError:
            logger.error(
                "Failed to save streamed turn", extra={"correlation_id": correlation_id}
            )
            yield _sse("error", StreamErrorEvent(detail="The answer was generated but couldn't be saved."))
            return

        yield _sse(
            "done",
            StreamDoneEvent(
                answer=answer,
                blocked=blocked,
                block_reason=block_reason,
                sources=sources,
                confidence=confidence,
                domains_used=domains_used,
                partial=partial,
                conversation_id=saved_conversation.id,
                correlation_id=correlation_id,
            ),
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
