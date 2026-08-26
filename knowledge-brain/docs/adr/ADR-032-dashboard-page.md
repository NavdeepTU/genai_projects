# ADR-032: The Dashboard page — real digest, honest placeholders

## Status
Accepted.

## Context
Build-order item 13's third planned page. CLAUDE.md's own frontend
spec names four things this page should show: total documents
ingested, recent queries, a retrieval accuracy trend, and cost per
query this month. Checking what the system actually tracks before
designing anything, the same discipline ADR-031 already applied to the
Query page, found the same shape of gap again: two of the four things
are backed by real, existing data, and two aren't tracked anywhere at
all. Total documents is a straightforward count against
`documents`/`document_permissions`. Recent queries already exist as
`query_made` entries in the append-only audit log, written by
`/query` every time someone asks a question — nothing new needed
there either. Retrieval accuracy has no ground-truth signal for a real
user's question; only the offline evaluation harness (build item 9)
has that, scored against fixture documents with known answers, and it
isn't run automatically or stored over time. Cost per query has no
token or dollar tracking anywhere in the system — that's squarely
build-order item 15 (LLM/RAG observability), not a Dashboard-page
concern.

## Options considered
For accuracy and cost, the same two-way fork each:
1. **Honest placeholder** — show the widget with a clear "not tracked
   yet" state naming exactly why, instead of a number.
2. **Compute something now** — for accuracy, persist the live
   confidence score `/query` already returns and plot its trend; for
   cost, instrument every OpenAI/Voyage call site with token counting
   and a pricing table to produce a real dollar figure.

For where documents get counted:
1. **Reuse `list_documents_for_user`** and take `len()` of the result.
2. **A dedicated `COUNT(*)` query.**

## Decision
Honest placeholders for both accuracy and cost, named explicitly, not
computed. A dedicated `count_documents_for_user` method using
`SELECT COUNT(*)`, not a reused list-and-count.

## Reasoning
The confidence-as-proxy option for accuracy was rejected specifically
because confidence and accuracy are different claims: confidence is
the reranker's own relevance judgment between a question and the
chunks it found, with no ground truth involved at all — it can be
high and still wrong, or low and still right. Plotting it under a
label that says "accuracy" would overstate what the number actually
means, exactly the kind of misleading-number trap this project has
now explicitly avoided twice (see ADR-031's own decision not to fake
streaming). Real accuracy tracking needs the evaluation harness's
ground-truth-checked results captured over time, which is a real
feature of its own — wiring the harness to run and store results
regularly, not a Dashboard-page addition.

Real cost tracking was rejected for the same build-order reason
ADR-031 already used for streaming and conversation history: it's a
genuine feature with its own scope (instrumenting every LLM/embedding/
reranking call site, a pricing table, likely a real observability tool
per CLAUDE.md's own naming of LangSmith or Langfuse as candidates for
item 15), not a small addition to a page. Building a rough version now
— counting requests and multiplying by an average — was also
considered and rejected as not worth doing at all: an approximate cost
number is arguably worse than an honest "not tracked," since it looks
authoritative while being wrong.

`count_documents_for_user` as its own `COUNT(*)` query, rather than
reusing `list_documents_for_user` and measuring the returned list, was
the one small efficiency decision here: the dashboard never needs the
actual document rows, only how many there are, and pulling every row's
full data across the network just to discard it and keep a number is
real, avoidable waste — small at today's document count, a real cost
difference once a user has thousands of documents.

## Consequences
- New `app/models/dashboard.py`: `DashboardResponse`
  (`document_count`, `recent_queries`, `correlation_id`), `RecentQuery`
  (`question`, `asked_at`).
- `DocumentRepository.count_documents_for_user` — same permission join
  every other document query already uses, a `COUNT(*)` instead of a
  `SELECT`.
- `AuditRepository` gains its first read method,
  `get_recent_queries_for_user` — the append-only guarantee was always
  specifically "no `UPDATE`/`DELETE`," never "no `SELECT`," so this
  doesn't touch that guarantee at all.
- New `GET /dashboard` endpoint, one combined response rather than the
  page making two separate round trips for document count and recent
  queries.
- New `frontend/app/page.tsx` — replacing the unmodified
  `create-next-app` boilerplate that had sat at the app's root since
  the very first frontend session, since the navbar's "Dashboard" link
  has always pointed at `/`, not a nested `/dashboard` route. Caught
  live, after first building the page at the wrong path
  (`app/dashboard/page.tsx`) without checking the navbar's existing
  routing convention first — moved to the correct location, the
  now-empty `app/dashboard/` directory removed. `dynamic =
  "force-dynamic"` applied from the start this time, the explicit
  habit named as a lesson at the end of the session that built the
  Document Library page.
- While preparing this session's tests, found and fixed a real
  scaffolding violation from the *previous* session: `/query`'s
  sources/confidence-building logic was sitting directly in the route
  handler in `app/api/query.py`, not a service — this project's own
  scaffolding rule is routes stay thin, business logic lives in
  services. Extracted into `RetrievalService.build_sources_and_confidence`,
  which also made it directly unit-testable without needing an HTTP
  test client this project has never used. Verified the extraction
  changed nothing about `/query`'s live behavior before or after.
- New tests: `tests/test_dashboard.py` (both new repository methods —
  permission-scoping, ordering, the `limit` parameter) and
  `tests/test_retrieval_service.py` (the newly-extracted
  `build_sources_and_confidence` — filename lookup and dedup,
  `confidence = None` specifically when the reranker was unavailable
  even with a real-looking score present, and the missing-document
  fallback). Test suite: 12 → 19 passing.

## Scale, cost, and on-call reality
This page adds no new external dependency and, unlike most recent
features, actually removes a small amount of future cost: counting
via `COUNT(*)` instead of transferring every document row scales
correctly as the document count grows, rather than getting linearly
more wasteful. The two placeholders are the honest, real remaining
cost of this feature: neither retrieval quality nor spend has any
visibility today beyond what a human manually runs (the eval harness)
or reads from an OpenAI/Voyage billing dashboard directly. That gap
doesn't get worse by building this page — it just becomes visible on
it, which is the point: a dashboard that silently omitted these two
rows entirely would look complete without being complete, while one
that shows them as explicitly untracked keeps the real gap in view
until item 15 closes it for real.
