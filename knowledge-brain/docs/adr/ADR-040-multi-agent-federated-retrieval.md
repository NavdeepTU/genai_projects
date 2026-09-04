# ADR-040: Multi-agent federated retrieval

## Status
Accepted.

## Context
Build-order item 17. CLAUDE.md's spec for this feature assumes "metadata
already stored per document" for domain classification — but no domain
concept existed anywhere in the codebase before this feature (confirmed
via a full search of `app/` for the word "domain," which returned
nothing). Before any multi-agent design could proceed, three
prerequisite questions had to be answered first: what a "domain" even
is, how a document gets assigned one, and whether a document can belong
to more than one at once.

## Options considered

**What a domain is, and how a document gets one:**
1. **A simple free-text category, set manually at upload, allowing
   multiple domains per document** — the user's own explicit choice.
2. An enumerated, admin-defined taxonomy fixed in advance.
3. Auto-detected by a classifier run at ingestion time, inferring the
   domain(s) from the document's own content.

**Domain storage:**
1. **A plain Postgres array column** (`domains VARCHAR[]`) directly on
   `Document`.
2. A separate many-to-many join table, matching the pattern
   `document_permissions` already uses for user access.

**How a domain-scoped retrieval agent actually works:**
1. **Reuse the existing single-domain `RetrievalService`, parameterized
   by a new optional `domain` filter** — each "agent" is just
   `RetrievalService.run_query(question, user_id, domain)`, running the
   exact same hybrid search → rerank → generate → guardrails pipeline,
   scoped to one domain.
2. Build a second, parallel retrieval pipeline specifically for the
   multi-domain case.

**How synthesis merges results across domains:**
1. **Each domain produces a complete, independent draft answer; a
   separate synthesis call merges the drafts** — matching CLAUDE.md's
   literal spec wording ("merges the per-domain answers").
2. Pool the raw retrieved chunks from every relevant domain into one
   shared context and run a single generation call over all of them.

**Failure isolation when one domain's retrieval fails:**
1. **Task-level: a safe-wrapper around each domain's `run_query` call,
   so one domain's exception can't stop the others inside
   `asyncio.gather`; synthesis proceeds with whichever domains
   succeeded, marked partial.**
2. Literal per-domain circuit breaker instances, matching CLAUDE.md's
   literal wording.

## Decision
Domains are a simple free-text category, set manually at upload,
allowing multiple domains per document, stored as a plain Postgres array
column on `Document`. A supervisor call (`classify_domains`) decides
which of a user's accessible domains a question needs. Zero or one
domain needed delegates straight to the existing single-domain
`RetrievalService.run_query`, parameterized by an optional `domain`
filter — unchanged, at the same cost as before this feature existed.
Two or more domains needed runs one full `RetrievalService.run_query`
pass per domain, concurrently, each producing its own complete draft
answer; a synthesis call (`synthesize_answers`) merges the drafts into
one answer, which gets one more moderation+injection safety pass before
it's returned. A failing domain is excluded via a task-level
safe-wrapper (`_run_one_domain_safely`), not a literal per-domain
circuit breaker — synthesis proceeds with whichever domains succeeded,
marked `partial`.

## Reasoning
Free-text, manual, multi-domain tagging was chosen because it's the
smallest thing that lets the rest of this feature exist at all — a
fixed taxonomy needs admin tooling that doesn't exist yet, and
content-based auto-classification is a separate feature with its own
accuracy bar, not something to bolt onto this one silently. The real
cost of "simple" is named plainly, not hidden: there's no vocabulary
control today. Two people tagging the same real category "HR" and
"Human Resources" produces two domains the classifier will never know
are the same thing, silently fragmenting retrieval.

The plain array column was chosen over a join table because a join
table would imply a level of structure — a `domains` table with real
rows, a place to rename or dedupe a domain in one move — that doesn't
exist and wasn't asked for. A join table buys referential integrity
that this feature, as scoped, has no actual use for; if domains ever
become a real managed entity (a fixed taxonomy, admin-editable), that's
the moment to introduce one, not before.

Reusing `RetrievalService` with a `domain` filter, instead of a second
pipeline, means every domain-scoped pass automatically inherits hybrid
search, reranking, document-level ACL (item 5), and both the input and
output guardrails (item 16) — all of it, for free, with zero duplicated
logic and zero risk of the two pipelines drifting apart over time. A
second pipeline would have had to reimplement or import all of that by
hand.

Full per-domain draft answers, merged by a separate synthesis call,
were chosen over chunk-pooling for two reasons: it's what CLAUDE.md's
spec literally asks for, and it's a real quality decision, not just
spec-following — each domain's chunks get reranked against a question
already narrowed to one domain, rather than being pooled with a
different domain's chunks where the two domains' vocabulary could
interfere with each other's relevance scoring. The honest cost: a
genuinely cross-domain question now pays for N complete pipeline passes
plus a merge call, not one pass over a slightly bigger context window.

Task-level failure isolation was chosen over literal per-domain circuit
breakers because this project's breakers are already one shared
instance per *external service* (`openai_embeddings`, Voyage
reranking, and so on) — a real outage doesn't care which domain asked,
so a second breaker instance per domain wrapping the same external
dependency would be redundant, and they'd all trip together anyway
since they're protecting the same underlying resource. The safe-wrapper
(`_run_one_domain_safely`) reaches the exact outcome CLAUDE.md's spec
asks for — one domain's failure can't take down the others, and
synthesis still returns a clearly-labeled partial answer — through the
mechanism this project's circuit-breaker architecture actually has,
instead of a parallel layer that would only exist to satisfy the
spec's literal wording. This was flagged to, and approved by, the user
before being built, not decided silently.

## Consequences
- `app/models/document.py`: new `domains: Mapped[list[str]]` column
  (`ARRAY(String)`, defaults to an empty list), plus the field on
  `DocumentUploadResponse` and `DocumentListItem`.
- `app/repositories/document_repository.py`: `create_document` now
  dedupes its `domains` argument (order-preserving) — the one place
  both upload paths converge, so neither has to dedupe separately.
  `find_similar_chunks`/`find_by_keyword` gained an optional `domain`
  filter, joining `Document` and narrowing with `Document.domains.any()`
  only when a domain is given. New `list_domains_for_user`, returning
  the distinct domains across documents a user can actually see —
  untagged documents and domains the user has no access to never
  appear, so the classifier is never offered a choice that isn't real.
- `app/services/ingestion_service.py`, `app/api/documents.py`,
  `app/mcp/server.py`: `domains` threaded through `create_document` end
  to end — a comma-separated form field on the REST route, a plain list
  on the MCP tool.
- `app/services/query_graph.py`, `app/services/retrieval_service.py`:
  `QueryState` gained `domain: str | None`; `run_query` accepts an
  optional `domain` and threads it into `_retrieve_node` and both of
  its `_safely` search helpers.
- New `app/services/domain_classification.py`
  (`classify_domains(question, available_domains)`) and
  `app/services/synthesis.py`
  (`synthesize_answers(question, domain_answers, partial)`) — both
  thin, circuit-breaker-wrapped LLM calls, matching this project's
  existing convention of not writing dedicated unit tests for that
  category of module (`moderation.py`, `injection_detection.py`, and
  now these two are tested only indirectly, through the service that
  orchestrates them).
- New `app/services/federated_retrieval_service.py`:
  `FederatedRetrievalService`, the new single entry point every caller
  uses, and `FederatedResult` (answer, sources, confidence,
  duration_ms, blocked, block_reason, domains_used, partial).
  `confidence` is always `None` on the multi-domain path — no single
  well-defined relevance score exists once several domains' reranked
  results have been merged into prose.
- `app/api/query.py`, `app/mcp/server.py`'s `ask_knowledge_base`:
  switched from `RetrievalService` to `FederatedRetrievalService`,
  adapting to `FederatedResult` instead of the raw `QueryState` dict.
- `eval/run_eval.py`: fixed a real, pre-existing bug found while
  touching this file — it called `ingestion.ingest_document(...)`, a
  method that no longer exists since ADR-030 split it into
  `create_document`/`process_document`. Deliberately **not** switched
  to `FederatedRetrievalService`: it needs the raw `QueryState`
  internals (`reranked_chunks`, `graph_context`) for scoring, which
  `FederatedResult` intentionally doesn't expose to normal callers, and
  since the eval fixtures carry no domain tags, the two are
  behaviorally identical for it today regardless.
- A manual `ALTER TABLE documents ADD COLUMN domains VARCHAR[] NOT NULL
  DEFAULT '{}';` was required against the real dev database — this
  project still has no migration tool (a known, standing gap), so
  `create_all()` alone can't add a column to an already-existing table.
- Frontend, same session: a "Domains (optional)" field added to the
  upload form (`components/upload-dropzone.tsx`), sending the same
  comma-separated string the backend already expects; domain badges
  now render on each document card. Required setting up Vitest +
  React Testing Library from nothing — this project had zero frontend
  test infrastructure before this — and extracting `DocumentCard` out
  of `app/documents/page.tsx` into its own `components/document-card.tsx`,
  since the page file transitively imports `next/headers` (via
  `lib/server-api`) and can't be imported in a non-Next.js test context.
- A code review the same session caught one real bug: domain badges
  keyed by `key={domain}` would collide on a repeated tag (typing
  "HR, HR"). Fixed at the same central point as the dedupe above —
  `DocumentRepository.create_document` — rather than patching the
  frontend render or each caller separately.
- Tests: 18 new backend tests (federated routing — single/multi-domain,
  classification-unavailable fallback, a failing domain marked partial,
  every domain failing, every domain's own guardrail blocking, the
  synthesized answer itself getting blocked; domain-filtered repository
  search; `list_domains_for_user`; domain dedup on create) plus 7 new
  frontend tests (field rendering, typing, FormData wiring, badge
  rendering). Backend suite: 52 → 70 passing.
- Verified live end to end, not just against mocks: uploaded two real
  domain-tagged documents (HR, Finance), asked a genuinely cross-domain
  question — synthesis correctly merged both domains' findings with
  `confidence` explicitly `null`. Asked a single-domain question —
  confirmed the cheap pass-through route with a real relevance score.
  Asked an off-topic question — confirmed the unrestricted fallback and
  a correct "I don't know." Also drove the frontend form in a real
  browser: typed a tag, uploaded a file, confirmed the badge rendered.

## Scale, cost, and on-call reality
A genuinely cross-domain question now costs roughly Nx the
single-domain latency and token cost — N concurrent domain-scoped
pipeline passes, each with its own embedding, rerank, generation, and
guardrail calls, plus one synthesis call, plus one more guardrails pass
on the merged answer. Confirmed live: ~11.8s for a 2-domain question
against ~5.5s for a single-domain one. The common case pays nothing
beyond one classification call, since domains are opt-in and most
documents remain untagged today — but that fraction shifts as domain
adoption grows, and the per-query cost split (ADR-038, LangSmith) is
where that shift will actually show up. The free-text domain model has
no vocabulary control, and nothing today detects or warns when two
near-duplicate domain names silently fragment what should be one
category — a real, un-addressed gap, not a hypothetical one. And the
"no migration tool" gap, first surfaced in an earlier session, showed
up again here exactly as expected — the third feature in a row needing
a hand-run `ALTER TABLE`, which makes the case for actually adopting
Alembic stronger each time it happens rather than weaker.

One gap in the failure-isolation story itself, found live rather than
assumed away: `_run_one_domain_safely` only catches `(CircuitOpenError,
RetrievalUnavailableError, OpenAIError)`, not a raw provider exception
a service can throw *before* its circuit breaker has actually tripped
open — confirmed live when Voyage AI's free-tier rate limit (3
requests/minute) was hit mid-verification and surfaced as an unhandled
500, not a graceful degradation. `_rerank_safely` itself only catches
`CircuitOpenError` too, a pre-existing gap this feature didn't
introduce — but this feature's task-level isolation inherits it with a
sharper consequence: one domain hitting this exact scenario would
propagate up through `asyncio.gather` uncaught and fail the whole
federated question, not just exclude that one domain the way the
design intends. Not fixed this session; named here rather than left for
whoever hits it next to rediscover.
