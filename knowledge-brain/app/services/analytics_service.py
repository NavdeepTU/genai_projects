from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from app.models.analytics import AnalyticsResponse, QueryVolumePoint, TopQuestion
from app.repositories.audit_repository import AuditRepository

TOP_QUESTIONS_LIMIT = 5
DEFAULT_WINDOW_DAYS = 30


class AnalyticsService:
    """Turns raw audit log entries into the trends the Analytics page shows.

    Reads existing data only — nothing here is a new source of truth,
    the same reasoning ADR-032 already used for the Dashboard.
    """

    def __init__(self, audit_repository: AuditRepository) -> None:
        self.audit_repository = audit_repository

    async def get_analytics(
        self, user_id: str, correlation_id: str, days: int = DEFAULT_WINDOW_DAYS
    ) -> AnalyticsResponse:
        """Aggregate this user's last N days of queries into volume, top questions, and latency."""
        entries = await self.audit_repository.get_query_entries_for_user(
            user_id, days=days, correlation_id=correlation_id
        )

        volume_by_date: dict = defaultdict(int)
        question_counts: Counter = Counter()
        durations: list[float] = []

        for entry in entries:
            volume_by_date[entry.timestamp.date()] += 1
            question_counts[entry.extra_data.get("question", "")] += 1
            duration = entry.extra_data.get("duration_ms")
            if duration is not None:
                durations.append(duration)

        # Zero-filled for every day in the window, not just days that had a
        # query — otherwise the chart spaces points evenly by array index,
        # and a real gap in usage (no queries for a week) would silently
        # compress into "two adjacent days," misrepresenting how sparse or
        # bursty usage actually was.
        today = datetime.now(UTC).date()
        query_volume = [
            QueryVolumePoint(date=day, count=volume_by_date.get(day, 0))
            for day in (today - timedelta(days=offset) for offset in range(days - 1, -1, -1))
        ]
        top_questions = [
            TopQuestion(question=question, count=count)
            for question, count in question_counts.most_common(TOP_QUESTIONS_LIMIT)
        ]
        avg_response_time_ms = sum(durations) / len(durations) if durations else None

        return AnalyticsResponse(
            query_volume=query_volume,
            top_questions=top_questions,
            avg_response_time_ms=avg_response_time_ms,
            correlation_id=correlation_id,
        )
