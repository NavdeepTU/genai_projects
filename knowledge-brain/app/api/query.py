from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.query import QueryRequest, QueryResponse
from app.repositories.document_repository import DocumentRepository
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    db: AsyncSession = Depends(get_db),
) -> QueryResponse:
    """Answer a question using retrieval-augmented generation."""
    service = RetrievalService(DocumentRepository(db))
    answer = await service.answer_question(request.question)
    return QueryResponse(answer=answer)
