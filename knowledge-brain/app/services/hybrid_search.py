import uuid

from app.models.document import Chunk

RRF_K = 60


def reciprocal_rank_fusion(
    vector_results: list[Chunk],
    keyword_results: list[Chunk],
    limit: int = 5,
) -> list[Chunk]:
    """Merge two independently-ranked chunk lists into one, by rank position.

    Each chunk's score is 1 / (RRF_K + its rank) in a given list (rank
    starts at 1), summed across whichever list(s) it appears in. A chunk
    found by both searches gets both contributions added together, so
    agreement between the two methods is what wins — not either method's
    raw, not-directly-comparable score (cosine distance vs. text rank).
    """
    scores: dict[uuid.UUID, float] = {}
    chunks_by_id: dict[uuid.UUID, Chunk] = {}

    for results in (vector_results, keyword_results):
        for rank, chunk in enumerate(results, start=1):
            scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (RRF_K + rank)
            chunks_by_id[chunk.id] = chunk

    ranked_ids = sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)
    return [chunks_by_id[chunk_id] for chunk_id in ranked_ids[:limit]]
