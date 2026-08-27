# ADR-033: The Analytics page — real timing, zero-filled trends, no new library

## Status
Accepted.

## Context
Build-order item 13's fourth planned page. CLAUDE.md's spec names four
things: query volume over time, top questions asked, retrieval
accuracy trends, and average response time. The same audit already
applied to the Query and Dashboard pages found the same shape of gap:
query volume and top questions are real, derivable from the audit
log's existing `query_made` entries; retrieval accuracy has the exact
same no-ground-truth gap ADR-032 already named for the Dashboard.
Average response time was different in kind — genuinely cheap to
close, since nothing needed is external infrastructure, just wall-clock
timing around one call site — so it was decided explicitly, not
defaulted to another placeholder.

A `/code-review` pass after the initial build surfaced seven real
findings, the most severe a genuine correctness bug: the query-volume
chart only received a data point for days that actually had a query,
and spaced points evenly by array index — a real gap in usage (no
queries for a week) rendered as if the surrounding days were
consecutive, silently misrepresenting how sparse or bursty usage
actually was.

## Options considered
For rendering the time-series chart and top-questions list:
1. **Hand-rolled inline SVG**, no new dependency.
2. **A charting library** (e.g. Recharts) — less code, but a new
   dependency on a project that has otherwise avoided adding libraries
   beyond Shadcn/Base UI.

For where response-time timing gets captured:
1. **Once, at the service level** (`RetrievalService.run_query`,
   wrapping the graph invocation) — both REST and MCP get it for free.
2. **Separately, in each caller** (`/query`'s route, MCP's
   `ask_knowledge_base`) — duplicated timing logic in two files.

For the query-volume chart's data shape, after the review finding:
1. **Zero-fill every day in the window**, so the array's index always
   corresponds 1:1 with a calendar date.
2. **Only emit points for days with actual activity** (the original
   implementation) — fewer points to transfer, but positionally
   meaningless without also carrying explicit dates the chart would
   need to space non-uniformly.

## Decision
Hand-rolled SVG, no new dependency. Timing captured once, in
`RetrievalService.run_query`. The query-volume array is zero-filled
for the full window.

## Reasoning
The charting decision followed this project's established pattern of
hand-rolling things itself (the circuit breaker, the upload progress
bars) rather than reaching for a library — a bar chart and a
proportional-width bar list are both simple enough that plain SVG and
`<div>` widths are less total complexity than learning and theming a
new dependency's API for two views.

Capturing timing once, at the service level, was the only real choice
once it was established that MCP's `ask_knowledge_base` writes to the
exact same `query_made` audit log `/query` does — a response-time
average that only ever saw REST traffic wouldn't be honest about
actual usage. That forced MCP off `answer_question` (a thin wrapper
that only returned the answer string) onto `run_query` (the full
state), which made `answer_question` dead code — deleted outright,
not left as an unused stub, the same "check every caller before a
refactor" discipline the previous session's MCP regression already
taught.

The zero-fill fix, found by `/code-review`, wasn't originally decided
as a fork — the first pass genuinely missed that the chart's
index-based bar spacing silently assumed one point per day, which
stopped being true the moment a real day had zero queries. Zero-filling
in `AnalyticsService`, not the frontend, was the correct layer for the
fix: the chart component shouldn't need to know how to reconstruct
missing calendar days from a sparse list — it should receive a
data shape where "index N" and "day N of the window" are always the
same thing, matching the contract its rendering logic already assumed.

## Consequences
- `app/services/query_graph.py`: `QueryState` gains `duration_ms`.
- `app/services/retrieval_service.py`: `run_query` times the graph
  invocation with `time.monotonic()`; `answer_question` deleted (no
  remaining callers after MCP switched to `run_query`).
- `app/repositories/audit_repository.py`: new
  `log_query_made(correlation_id, user_id, question, duration_ms)` —
  a named wrapper around `log_action`, the one place both `/query` and
  MCP's tool now write from, replacing two independently hand-built
  `extra_data` dicts that had already drifted once in this same
  session (one call site got `duration_ms` before the other did, until
  this method existed). New `get_query_entries_for_user(user_id, days,
  limit, correlation_id)` — `limit` a safety cap (5000, newest-first),
  not real pagination; `correlation_id` accepted as a plain parameter,
  not read via `get_correlation_id()`, because that function lives in
  `app.core.middleware`, which itself imports `AuditRepository` —
  importing it back here would be a circular import, not a stale
  contextvar the way ADR-030's background-task case was.
- `app/services/analytics_service.py`: new `AnalyticsService`, grouping
  by day (zero-filled across the full window), counting exact
  question-text matches (a real, named limit — no semantic
  clustering), and averaging `duration_ms` only across entries that
  have it, so older audit rows from before this feature degrade
  gracefully rather than corrupting the average toward zero.
- `app/api/analytics.py`: new thin `GET /analytics`.
- Frontend: `frontend/app/analytics/page.tsx`, `query-volume-chart.tsx`
  (hand-rolled SVG, exports `NO_QUERIES_MESSAGE`), and three components
  extracted for real reuse found by the review, not speculative
  sharing: `stat-tile.tsx` (Dashboard + Analytics), `progress-bar.tsx`
  (upload dropzone + Analytics' top-questions bars), `list-card.tsx`
  (Dashboard's recent queries + Analytics' top questions).
- Test suite: 19 → 25 passing (5 new for `AnalyticsService`/repository
  behavior, 1 replacing a test that had asserted the pre-fix, buggy
  single-point-per-day shape).
- Verified live: `/analytics` returns 30 real, chronological,
  zero-filled points; a real query's `duration_ms` (~9s, a full
  RAG pipeline call) shows up in the next `/analytics` call's average;
  both fixed frontend components render correctly in the browser,
  light and dark mode, across Analytics, Dashboard, and Documents.

## Scale, cost, and on-call reality
Zero-filling a 30-day window is fixed-size work regardless of actual
query volume — cheap, and the reason a rollup table isn't needed yet
for this specific shape. The real remaining cost is what the 5000-row
safety cap admits: a user who asks more than ~166 questions/day,
every day, for a month would start silently losing the oldest entries
in that window from both the volume chart and the top-questions list,
with no error or indication it happened — acceptable at today's usage,
a real gap to revisit with a proper rollup or DB-side aggregation once
usage is anywhere near that. Timing wraps the *entire* graph
invocation, including retry loops and graph-context lookups, not just
the final generation call — the right thing to average for "true
end-user wait time," but it means a slow reranker retry inflates the
number the same way a slow LLM call would, worth remembering before
treating a surprising average as necessarily a generation-side problem.
