from datetime import date

from pydantic import BaseModel


class QueryVolumePoint(BaseModel):
    """How many questions were asked on one day, for the volume chart."""

    date: date
    count: int


class TopQuestion(BaseModel):
    """One frequently-asked question and how many times it was asked, verbatim.

    Grouped by exact question text — two differently-phrased questions
    with the same intent are counted separately, not merged. A real,
    named limit, not an oversight: merging by meaning would need the
    same embedding/similarity machinery retrieval already uses, applied
    to a different problem.
    """

    question: str
    count: int


class AnalyticsResponse(BaseModel):
    """A trends digest, over the last 30 days — existing audit log data, aggregated."""

    query_volume: list[QueryVolumePoint]
    top_questions: list[TopQuestion]
    avg_response_time_ms: float | None
    correlation_id: str
