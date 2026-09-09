import uuid

from app.models.document import Chunk
from app.services.hybrid_search import RRF_K, reciprocal_rank_fusion


def _chunk(chunk_id: uuid.UUID | None = None) -> Chunk:
    return Chunk(
        id=chunk_id or uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_index=0,
        text="chunk text",
        embedding=[0.1] * 1536,
    )


def test_rrf_favors_a_chunk_found_by_both_searches_over_one_found_by_only_one():
    """A chunk both searches agree on should outrank one only vector search found,
    even though the vector-only chunk was ranked #1 in its own list.
    """
    agreed = _chunk()
    vector_only = _chunk()

    result = reciprocal_rank_fusion(
        vector_results=[vector_only, agreed],
        keyword_results=[agreed],
    )

    assert result[0].id == agreed.id


def test_rrf_orders_purely_by_rank_position_not_which_list_a_chunk_came_from():
    """The formula only ever looks at rank position within each list — a chunk
    ranked #2 in keyword results should still outscore one ranked #5 in vector
    results, confirmed by computing the exact expected score by hand.
    """
    second_in_keyword = _chunk()
    fifth_in_vector = _chunk()
    keyword_filler = _chunk()
    vector_filler = [_chunk() for _ in range(4)]

    result = reciprocal_rank_fusion(
        vector_results=[*vector_filler, fifth_in_vector],
        keyword_results=[keyword_filler, second_in_keyword],
        limit=10,
    )

    # second_in_keyword: 1/(60+2) ≈ 0.01613. fifth_in_vector: 1/(60+5) ≈ 0.01538.
    ids = [c.id for c in result]
    assert ids.index(second_in_keyword.id) < ids.index(fifth_in_vector.id)


def test_rrf_respects_the_limit_parameter():
    chunks = [_chunk() for _ in range(10)]

    result = reciprocal_rank_fusion(vector_results=chunks, keyword_results=[], limit=3)

    assert len(result) == 3
    # Limit keeps the top-ranked (lowest rank number → highest score) chunks.
    assert [c.id for c in result] == [c.id for c in chunks[:3]]


def test_rrf_handles_one_search_returning_nothing():
    only_result = _chunk()

    result = reciprocal_rank_fusion(vector_results=[only_result], keyword_results=[])

    assert [c.id for c in result] == [only_result.id]


def test_rrf_handles_both_searches_returning_nothing():
    result = reciprocal_rank_fusion(vector_results=[], keyword_results=[])

    assert result == []


def test_rrf_k_constant_matches_the_documented_value():
    """A regression guard on RRF_K itself — the formula's own docstring cites
    this constant, so a silent change here would make the docstring's worked
    example, and every score comparison above, quietly wrong.
    """
    assert RRF_K == 60
