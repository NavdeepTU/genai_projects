# ADR-011: Hybrid search — Postgres full-text search, merged via Reciprocal Rank Fusion

## Status
Accepted

## Context
Pure vector similarity search is good at finding conceptually related
text, but weak at guaranteeing exact matches on specific terms — error
codes, product IDs, version numbers, rare proper nouns — since embedding
models represent general meaning, not exact lexical identity. Two
decisions were needed: what to use for keyword search, and how to
combine its results with the existing vector search.

## Decision 1: Postgres full-text search, not a dedicated search engine

### Options considered
1. **Postgres full-text search** — built-in `tsvector`/`tsquery` with
   `ts_rank`, computed on the existing `chunks` table.
2. **A dedicated search engine** — e.g. Elasticsearch or OpenSearch.

### Decision
Postgres full-text search (Option 1).

### Reasoning
Same reasoning as ADR-002 (pgvector over Qdrant): keeping keyword search
in the same database as everything else means no new infrastructure, one
connection, and no second system to keep in sync. A dedicated search
engine is genuinely more powerful at large scale, but is real
infrastructure overhead unjustified at our current size — the same
"start simple, add complexity once the pain is real" pattern used
throughout this project.

## Decision 2: Merge results with Reciprocal Rank Fusion (RRF)

### Options considered
1. **Reciprocal Rank Fusion** — score each chunk by `1/(k + rank)` in
   each list it appears in, summed across lists.
2. **Normalize and combine raw scores** — e.g. min-max normalize cosine
   distance and `ts_rank` separately, then average or weight them.
3. **Simple deduplication with a fixed priority** — e.g. always prefer
   vector results, only fall back to keyword results to fill remaining
   slots.

### Decision
Reciprocal Rank Fusion (Option 1).

### Reasoning
Cosine distance and `ts_rank` are measured on completely different,
incomparable scales — there's no principled way to combine "0.23 cosine
distance" with "1.8 text relevance" directly (Option 2). Normalizing both
to a common scale is possible but adds real complexity and tuning
(choosing weights, handling edge cases like an empty result list) for a
technique whose main benefit — score comparability — RRF gets for free by
working with rank position instead of raw scores. A fixed-priority
approach (Option 3) would silently favor one search method over the
other by design, defeating the actual purpose of combining them. RRF is
also simple enough to implement correctly by hand, consistent with how
the rest of this project has been built.

## Consequences
- `RetrievalService.answer_question` now performs two database queries
  per request instead of one — both run sequentially against the same
  `AsyncSession` (see the "future optimizations" note in
  `docs/PROGRESS.md` for a planned, deferred parallelization using
  separate sessions).
- `RRF_K = 60` is the standard constant from the original RRF research;
  changing it would change how much rank position vs. list-agreement
  affects the final ranking, but hasn't been tuned for this project's
  specific data.
- Neither search result set is guaranteed to have `limit` chunks —
  keyword search is a real filter and can return fewer matches (or zero)
  even when vector search always returns exactly `limit`.
