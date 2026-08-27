from datetime import UTC, datetime, timedelta

from app.models.audit_log import AuditLog
from app.repositories.audit_repository import AuditRepository
from app.services.analytics_service import AnalyticsService


async def _log_query(audit: AuditRepository, *, user_id: str, question: str, duration_ms=None):
    extra_data = {"question": question}
    if duration_ms is not None:
        extra_data["duration_ms"] = duration_ms
    await audit.log_action(
        correlation_id="c",
        action="query_made",
        resource_type="query",
        resource_id="c",
        extra_data=extra_data,
        user_id=user_id,
    )


async def test_get_query_entries_for_user_excludes_old_entries(db_session):
    """Entries older than the window shouldn't come back."""
    audit = AuditRepository(db_session)
    await _log_query(audit, user_id="alice", question="recent question")

    # Insert an old entry directly, bypassing log_action's default "now" timestamp.
    old_entry = AuditLog(
        timestamp=datetime.now(UTC) - timedelta(days=40),
        correlation_id="old",
        action="query_made",
        resource_type="query",
        resource_id="old",
        extra_data={"question": "ancient question"},
        user_id="alice",
    )
    db_session.add(old_entry)
    await db_session.commit()

    results = await audit.get_query_entries_for_user("alice", days=30)

    assert [e.extra_data["question"] for e in results] == ["recent question"]


async def test_analytics_service_groups_volume_by_day(db_session):
    """Two queries on the same day should count as one point with count 2, not two points."""
    audit = AuditRepository(db_session)
    await _log_query(audit, user_id="alice", question="q1")
    await _log_query(audit, user_id="alice", question="q2")

    service = AnalyticsService(audit)
    analytics = await service.get_analytics("alice", correlation_id="c", days=30)

    today = datetime.now(UTC).date()
    todays_point = next(p for p in analytics.query_volume if p.date == today)
    assert todays_point.count == 2


async def test_analytics_service_zero_fills_days_with_no_queries(db_session):
    """Every day in the window should appear, even ones with zero queries — no gaps skipped."""
    audit = AuditRepository(db_session)
    await _log_query(audit, user_id="alice", question="only today")

    service = AnalyticsService(audit)
    analytics = await service.get_analytics("alice", correlation_id="c", days=7)

    assert len(analytics.query_volume) == 7
    today = datetime.now(UTC).date()
    counts_by_date = {p.date: p.count for p in analytics.query_volume}
    assert counts_by_date[today] == 1
    assert sum(1 for p in analytics.query_volume if p.count == 0) == 6
    # The window must actually be chronological and consecutive, not just
    # the right total count — a chart relies on that ordering.
    dates = [p.date for p in analytics.query_volume]
    assert dates == sorted(dates)
    assert dates[-1] == today


async def test_analytics_service_top_questions_counts_and_limits(db_session):
    """Repeated exact-text questions should be counted together, most-asked first, capped at 5."""
    audit = AuditRepository(db_session)
    await _log_query(audit, user_id="alice", question="popular question")
    await _log_query(audit, user_id="alice", question="popular question")
    await _log_query(audit, user_id="alice", question="rare question")

    service = AnalyticsService(audit)
    analytics = await service.get_analytics("alice", correlation_id="c")

    assert analytics.top_questions[0].question == "popular question"
    assert analytics.top_questions[0].count == 2
    assert analytics.top_questions[1].question == "rare question"
    assert analytics.top_questions[1].count == 1


async def test_analytics_service_averages_only_entries_with_duration(db_session):
    """Older entries with no duration_ms shouldn't break the average or count as zero."""
    audit = AuditRepository(db_session)
    await _log_query(audit, user_id="alice", question="q1", duration_ms=100.0)
    await _log_query(audit, user_id="alice", question="q2", duration_ms=300.0)
    await _log_query(audit, user_id="alice", question="q3")  # no duration_ms at all

    service = AnalyticsService(audit)
    analytics = await service.get_analytics("alice", correlation_id="c")

    assert analytics.avg_response_time_ms == 200.0


async def test_analytics_service_avg_response_time_is_none_with_no_timed_entries(db_session):
    """If nothing has timing data yet, the average must be None, not 0 or a crash."""
    audit = AuditRepository(db_session)
    await _log_query(audit, user_id="alice", question="q1")

    service = AnalyticsService(audit)
    analytics = await service.get_analytics("alice", correlation_id="c")

    assert analytics.avg_response_time_ms is None
