from datetime import datetime

from pydantic import BaseModel


class RecentQuery(BaseModel):
    """One past question this user asked, for the dashboard's recent-activity list."""

    question: str
    asked_at: datetime


class DashboardResponse(BaseModel):
    """A summary digest for the dashboard page — no new data, just existing data compacted."""

    document_count: int
    recent_queries: list[RecentQuery]
    correlation_id: str
