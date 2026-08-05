# ADR-012: Degrade gracefully when one half of hybrid search fails

## Status
Accepted

## Context
`RetrievalService.answer_question` runs two independent database queries —
vector search and keyword search — before merging their results with
Reciprocal Rank Fusion. Before this decision, a failure in *either* query
propagated straight up and failed the whole request, even when the other
query had already returned good results.

## Options considered
1. **Fail the whole request** — current (prior) behavior: any exception
   from either search aborts `answer_question` entirely.
2. **Retry the failed search** — catch the failure and immediately retry
   the same query, possibly with backoff, before giving up.
3. **Proceed with whichever search succeeded** — catch each search's
   failure independently, fall back to an empty result for that one, and
   only fail the request if *both* searches fail.

## Decision
Option 3 — proceed with whichever search succeeded.

## Reasoning
Retrying (Option 2) is the intuitive-seeming choice but is often the wrong
one: if a query failed because the database is genuinely under load,
retrying immediately adds more load to an already-struggling system — a
retry storm — instead of relieving it. There's no backoff/retry pattern
anywhere else in this codebase either, so it would be new complexity
solving a problem that has a simpler answer.

Proceeding with one search's results isn't a workaround bolted on top of
Reciprocal Rank Fusion — it's exactly what the algorithm already does
correctly. A chunk found by only one search is already a fully legitimate
case in `reciprocal_rank_fusion` (see ADR-011's consequences); it's
included, just without the score boost a chunk both searches agree on
gets. Falling back to a single, possibly-empty list needs zero new logic
in the fusion function itself.

This also matches a pattern the project already committed to elsewhere:
the circuit breaker (ADR-010) exists specifically to degrade gracefully
instead of letting one failing dependency cascade into a total outage.
Applying the same philosophy to the two DB queries, instead of inventing
a different one, keeps the codebase's failure-handling story consistent.

## A subtlety discovered while implementing this
Both searches share one `AsyncSession` (see ADR-011's consequences on why
they run sequentially, not concurrently). Catching a failed search's
exception isn't sufficient on its own — Postgres marks the whole
transaction as aborted after any query fails within it, and refuses any
further queries on that same session until an explicit `rollback()`.
Without it, the *second* search would also fail, not because anything was
wrong with it, but purely because the connection was still in a broken
state from the first failure.

Adding that `rollback()` call introduced a second, non-obvious bug, caught
only by actually running a test rather than by reading the code: SQLAlchemy's
`Session.rollback()` expires every object still tracked by the session —
including chunks from the *other*, already-successful search, fetched
*before* the failure. The next access to one of those chunks' columns
(e.g. `chunk.text`, read after both searches finish) then silently tries
to reload it from the database, which isn't safe outside an `await`-ed
call and raises (`MissingGreenlet`) instead. The fix: detach each search's
chunks from the session (`session.expunge()`) immediately after fetching
them, before anything else has a chance to roll the session back and
invalidate them.

## Consequences
- `DocumentRepository` gained two new methods: `rollback()` (resets an
  aborted transaction so the other search can still run) and `detach()`
  (protects already-fetched chunks from being invalidated by a later
  rollback).
- `RetrievalService.answer_question` now raises a new
  `RetrievalUnavailableError` only when *both* searches fail — not when
  either search legitimately returns zero matches, which is a distinct,
  unremarkable outcome (see ADR-004). Distinguishing "failed" from
  "genuinely empty" required tracking a separate boolean per search
  rather than checking whether the result list is empty.
- `app/api/query.py` catches `RetrievalUnavailableError` the same way it
  already catches `CircuitOpenError`, returning a `503` with a plain
  message instead of a raw error — reusing an existing response pattern
  rather than adding a new one.
- Verified with a throwaway script (not part of the permanent test suite,
  which still doesn't exist — see the project's long-standing "no
  automated tests yet" gap) that force-fails each search independently:
  confirmed a single failure degrades gracefully, and a double failure
  raises `RetrievalUnavailableError` as expected.

## Scale, cost, and on-call reality
This directly changes what an on-call engineer would see during a partial
outage. Before this ADR, a keyword-search-only problem (e.g. the missing
GIN index — see ADR-002 — turning slow under load) would show up as
*every single query failing*, a maximally alarming signal that overstates
the actual damage. After this ADR, the same problem shows up as degraded
answer quality (RRF running on vector-only results) with an error log per
failed search, a more accurate signal, but a quieter one — it requires
someone to actually be watching error logs or a dashboard tracking
per-search failure rates to notice at all, rather than a flood of 500s
forcing the issue. That trade (fewer loud failures, more silent
degradation) is deliberate, but worth naming: it raises the bar for what
monitoring needs to exist before this failure mode is something anyone
would actually catch in practice — today, nothing does.

Cost is effectively zero — `rollback()` and `expunge()` are both
in-process session operations, no new infrastructure, no added latency
on the successful path. The real cost paid here was engineering time
catching the second bug (the session-expiry issue), which is exactly the
kind of subtle, hard-to-spot-by-reading-code defect that justifies
writing even a throwaway test before considering a fix like this done.
