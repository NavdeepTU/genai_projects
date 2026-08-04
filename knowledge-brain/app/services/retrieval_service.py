from app.core.config import get_settings
from app.repositories.document_repository import DocumentRepository
from app.services.embedding import embed_chunks
from app.services.generation import generate_answer
from app.services.hybrid_search import reciprocal_rank_fusion

settings = get_settings()


class RetrievalService:
    """Answers a question using retrieval-augmented generation (RAG).

    Embeds the question, finds the most relevant stored chunks via
    hybrid search (vector + keyword), then asks an LLM to answer using
    only those chunks — mirroring IngestionService's role as the one
    place that knows step order.
    """

    def __init__(self, repository: DocumentRepository) -> None:
        self.repository = repository

    async def answer_question(self, question: str) -> str:
        """Run one question through hybrid retrieval, then generation."""
        [query_embedding] = await embed_chunks([question])

        # Run sequentially, not concurrently: both share one AsyncSession,
        # which isn't safe for two queries running at the same time.
        vector_chunks = await self.repository.find_similar_chunks(
            query_embedding, limit=settings.retrieval_top_k
        )
        keyword_chunks = await self.repository.find_by_keyword(
            question, limit=settings.retrieval_top_k
        )

        chunks = reciprocal_rank_fusion(vector_chunks, keyword_chunks, limit=settings.retrieval_top_k)
        context_chunks = [chunk.text for chunk in chunks]
        return await generate_answer(question, context_chunks)
