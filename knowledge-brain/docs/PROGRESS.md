# Knowledge Brain — Progress Log

This tracks the project from its actual starting point (an empty repo,
zero dependencies, zero code) forward. Each session gets its own entry,
appended below — nothing here gets rewritten as "current state," it's a
history.

---

## Session: 2026-08-04 — Project kickoff through Feature 2

Started from a completely empty project: scaffolded folders existed
(`app/api`, `app/core`, `app/models`, `app/services`, `app/repositories`)
but every file in them was empty, no dependencies were installed, and no
commits existed yet.

### Timeline

1. **Project setup.** Chose `uv` + `pyproject.toml` for dependency
   management over plain `pip`/`requirements.txt` or Poetry. Installed
   `uv` via Homebrew, initialized the project, cleaned up the generic
   `src/knowledge_brain` scaffold `uv init` created by default (it didn't
   match this project's `app/` layout).

2. **Feature 1 — Document ingestion pipeline.** Built, in order:
   `app/core/config.py` (settings via pydantic-settings), `app/core/database.py`
   (async SQLAlchemy engine/session), `app/models/document.py`
   (`Document`/`Chunk` models with a pgvector embedding column),
   `app/repositories/document_repository.py`, `app/services/chunking.py`,
   `app/services/embedding.py` (OpenAI), `app/services/extraction.py`
   (PDF + .txt), `app/services/ingestion_service.py` (orchestration),
   `app/api/documents.py`, and `app/main.py`.
   - Chose to process uploads synchronously for now rather than adding
     Kafka immediately (ADR-001).
   - Chose Postgres + pgvector over Qdrant for now (ADR-002).
   - Ran Postgres in Docker rather than natively (ADR-003) — hit a real
     port conflict with an already-running native Postgres install
     during setup, resolved by moving to port 5433.
   - Hit and fixed a real bug: `uploaded_at` was stored timezone-aware in
     Python but the database column was timezone-naive, causing every
     insert to fail until the column type was corrected.
   - Verified end-to-end: uploaded a real `.txt` file through the running
     server and confirmed it landed in Postgres as a document with one
     chunk and a 1536-dimension embedding.

3. **Side quest — voice output tooling.** Built `/speak` and `/pause` as
   custom global Claude Code commands, using macOS's `say` command with
   an Enhanced-quality voice, so responses can be read aloud on demand.
   Fixed a bug afterward where a paused-then-resumed `say` process could
   fail to exit cleanly.

4. **First commit and push.** Committed ingestion pipeline work and
   pushed to `origin/main` on GitHub.

5. **Feature 2 — Retrieval + answer generation.** Built
   `find_similar_chunks` on the repository (pgvector cosine-similarity
   search), `app/services/generation.py` (LLM answer generation via
   gpt-4o-mini), `app/services/retrieval_service.py` (orchestration), and
   `app/api/query.py`.
   - Chose cosine similarity over L2 distance / inner product (ADR-006).
   - Chose gpt-4o-mini over gpt-4o for cost/speed, grounded Q&A doesn't
     need gpt-4o's extra reasoning power (ADR-005).
   - Explicitly instructed the LLM to say "I don't know" rather than
     guess, to guard against hallucination (ADR-004).
   - Verified end-to-end: a real question returned a correctly grounded
     answer; an unrelated question correctly returned "I don't know."

6. **Second commit and push.** Committed and pushed retrieval/generation
   work.

7. **Documentation.** Wrote `docs/ARCHITECTURE.md` (kept current after
   each feature) and six ADRs (`docs/adr/ADR-001` through `ADR-006`).
   Built a visual build-status dashboard as a published Claude artifact,
   updated after each feature.

8. **Azure deployment discussion.** Discussed whether to defer Azure/CI-CD
   until the product is feature-complete. Landed on: for the stated goal
   of "hands-on Azure experience" specifically, deploying the current
   small system now is actually better for learning than waiting — not
   yet started.

9. **CLAUDE.md overhaul.** Replaced the project's `CLAUDE.md` with a
   significantly expanded version, adding Azure as the target cloud
   platform and eight "non-negotiable" enterprise requirements (PII
   detection, document-level access control, audit logging, correlation
   IDs, circuit breakers, an API gateway via Azure API Management, secrets
   via Key Vault, resource tagging). This directly conflicts with the
   "start simple, add complexity when needed" reasoning behind every ADR
   written so far — flagged, not yet resolved.

10. **Documentation restructuring.** Added `docs/INTERVIEW_PREP.md`
    (populated with plain-language Q&A for both completed features) and
    moved `PROGRESS.md` into `docs/`. Applied the same two changes to the
    sibling projects `agent-ops-platform` and `ai-data-analyst`
    (scaffolds only there — no features built in either yet).

### What I struggled with
- Mixed up "pgvector is a separate database" — needed a second pass to
  understand it's just a column type inside the same Postgres table, not
  a second system to keep in sync.
- Assumed a hash map could speed up similarity search at scale — needed
  correction that hash maps only do exact-key lookups, and the real fix
  is an approximate-nearest-neighbor index like HNSW.
- Needed a full, from-scratch re-explanation of how PDF text extraction
  actually works, and specifically why a scanned PDF page has *zero*
  extractable text (it's one embedded photo, not character data) — this
  took a couple of passes before it landed.

### Concepts to revisit
- Vector indexes (HNSW specifically) — discussed conceptually as a future
  fix, never actually implemented. Worth reading up on before we hit real
  scale.
- The three pgvector similarity metrics (cosine, L2, inner product) —
  understand cosine now, but the other two are still fairly surface-level.
- The new enterprise requirements from the updated `CLAUDE.md` (PII
  detection, ACL, audit logging, circuit breakers, correlation IDs) —
  none of these are understood in depth yet, and we haven't decided
  whether to retrofit the existing two features or apply them only
  going forward.

### What's next
- Decide: retrofit ingestion + retrieval to meet the new enterprise
  requirements, or treat them as applying only to future features.
- Still no automated test suite (`tests/` is empty) — a real gap, flagged
  but not yet addressed.
- Azure deployment — discussed as a legitimate hands-on-learning goal
  independent of project completeness; not started.
- Continue the build order: hybrid search is next up if we stick to the
  original sequence.

---

## Session: 2026-08-04 (continued) — Retrofit scope + correlation IDs started

### What we built
- **Resolved the "retrofit or not" question left open above.** Found a
  real contradiction inside the new `CLAUDE.md`: the Enterprise
  Requirements section demands all 8 items "from the start," but the
  file's own Build order section still lists PII detection and ACL as
  later steps (7 and 8). Resolved by splitting the 8 requirements: defer
  PII detection and ACL to their existing build-order steps (ACL is
  meaningless with no auth model yet); defer API Gateway/Key Vault until
  an actual Azure deployment exists; add correlation IDs, the audit log,
  and circuit breakers now, since all three are self-contained additions
  to existing code. Written up as ADR-007.
- **Correlation IDs — started, not finished.** Built
  `app/core/middleware.py`: a `ContextVar`-based middleware that
  generates (or reuses) a correlation ID per request, makes it available
  anywhere during that request via `get_correlation_id()`, and echoes it
  back as an `X-Correlation-ID` response header. Explained end to end.
  **Not yet done:** registering the middleware in `main.py`, adding
  `correlation_id` to `DocumentUploadResponse`/`QueryResponse`, and an
  unanswered check question (why `ContextVar` instead of
  `request.state`) — pick this back up next session before moving on to
  audit logging or circuit breakers.
- **Documentation restructuring**, applied consistently across all three
  sibling projects (knowledge-brain, agent-ops-platform,
  ai-data-analyst): `PROGRESS.md` moved into `docs/`, `docs/INTERVIEW_PREP.md`
  added, and `/start-session` / `/end-session` custom commands adopted as
  the standard way sessions start and close (replacing the old manual
  "Session Start Ritual" and ad-hoc doc updates).
- `docs/pipeline-status.html` moved out of the temporary session
  scratchpad into a permanent home at `docs/pipeline-status.html`, kept
  in sync with the same hosted artifact URL as before.

### What I struggled with
- Nothing new conceptually this stretch — mostly a planning and
  housekeeping session rather than new technical ground.

### Concepts to revisit
- Still owe a real answer to: why use a `ContextVar` for the correlation
  ID instead of `request.state`, which FastAPI also supports for
  per-request data? Left as an open question going into next session.
- The audit log and circuit breaker patterns haven't been explained yet
  at all — both are next after correlation IDs are finished.

### What's next
- Finish correlation IDs: wire the middleware into `main.py`, add
  `correlation_id` to both response models, answer the open
  `ContextVar` vs. `request.state` question.
- Then: append-only audit log, then circuit breakers on the OpenAI calls
  (per ADR-007's ordering).
- Still no automated test suite — carried over from before, still open.
- PII detection, ACL, APIM, and Key Vault remain intentionally deferred
  per ADR-007 — not forgotten, just not yet.

---

## Session: 2026-08-04 (continued) — ADR-007's three deferred items, finished

### What we built
- **Correlation IDs — finished.** Wired `correlation_id_middleware` into
  `main.py`, added `correlation_id` to both `DocumentUploadResponse` and
  `QueryResponse`, and switched both routes to build their response
  explicitly rather than auto-converting from the ORM object (which has
  no `correlation_id` attribute of its own). Verified live: an
  auto-generated ID and a client-supplied `X-Correlation-ID` header both
  correctly appear in the matching response body and header.
- **Append-only audit log — built.** New `AuditLog` model and
  `AuditRepository` (insert-only by design — no update/delete methods
  exist in the code). Wired into both routes: uploads log
  `document_upload`, queries log `query_made`. Verified live by querying
  `audit_log` directly after both actions. Honest gap noted (and
  documented in ADR-009): true database-level tamper-proofing isn't
  possible yet, since our local Postgres role is a superuser and bypasses
  permission restrictions — enforced at the code level only for now.
- **Circuit breaker — built.** A hand-written `CircuitBreaker` class
  (closed/open/half-open, rolling failure window, cooldown recovery),
  wrapping both OpenAI call sites with two independent instances.
  Verified the state machine directly with a standalone script (3
  failures → opens → 4th call rejected without trying → recovers after
  cooldown), then confirmed normal requests still work unaffected through
  the live server. `query.py` now catches an open circuit and returns a
  clean `503` instead of a raw crash; ingestion needed no new handling
  since its existing failure handling already covers it.
- Four new ADRs: ADR-008 (ContextVar), ADR-009 (audit logging placement
  and enforcement), ADR-010 (custom circuit breaker, per-call-site
  fallback handling).
- All of ADR-007's "add now" list is complete — correlation IDs, audit
  logging, and circuit breakers are done, verified, and documented.

### What I struggled with
- Initially explained *why* `ContextVar` is needed correctly in outline,
  but the first two answers were vague/circular rather than specific —
  took a "what would you literally have to change" reframing before it
  fully landed.
- Described the multi-server circuit breaker problem backwards at first —
  assumed shared state would incorrectly link unrelated servers' failures
  together, when the real issue is the opposite: there's currently *no*
  sharing at all, so protection doesn't scale correctly across instances.
  Corrected after seeing exactly where in the code state lives (a plain
  per-process Python variable).
- Slipped back into thinking of pgvector as a separate table/store at one
  point (asked "how are the chunks table and pgvector linked"), even
  after this was already cleared up earlier — worth watching for again.

### Concepts to revisit
- The distinction between "code enforces X" and "the database enforces
  X" — this came up twice now (the audit log, and briefly the read-only
  connection pool idea from a sibling project's CLAUDE.md) and is worth
  being able to explain crisply: code-level checks can be bypassed by
  anything that skips the code path; only a database-level permission
  is enforced no matter what connects.
- Multi-instance/shared-state problems in general — the circuit breaker
  is the second time this session a "works great on one process, breaks
  across many" gap showed up (the first being in-memory rate limiting
  concerns implied by APIM). Worth a deeper look before Feature 10.

### What's next
- Continue the original build order: hybrid search is next if we stick
  to the plan.
- Still no automated test suite — carried over multiple sessions now,
  the longest-standing open gap.
- PII detection, ACL, APIM, and Key Vault remain intentionally deferred
  per ADR-007.
- Worth deciding, at some point: does the circuit breaker's per-process
  limitation matter enough to fix now, or is it a "revisit once we
  actually run more than one instance" item?

---

## Session: 2026-08-04 (continued) — Feature 3: Hybrid search

### What we built
- **Hybrid search — built and verified.** Added `find_by_keyword` to the
  repository (Postgres full-text search via `tsvector`/`plainto_tsquery`/`ts_rank`,
  computed on the fly, no persisted index yet) and a new
  `app/services/hybrid_search.py` implementing Reciprocal Rank Fusion by
  hand to merge vector and keyword result lists. `retrieval_service.py`
  now runs both searches (sequentially — they share one `AsyncSession`,
  which isn't safe for concurrent queries) and merges before generation.
  Verified live: a query for an exact error code embedded in a test
  document returned the correct answer (proving keyword search
  contributed), and a purely conceptual question still worked with no
  regression to plain vector search.
- ADR-011 documents both decisions: Postgres full-text search over a
  dedicated engine, and RRF over normalizing/combining raw scores.
- Rewrote `README.md` properly — it was thin and, worse, its "run it
  locally" steps were actually missing two required steps (enabling the
  pgvector extension, creating the tables), which would have broken for
  anyone following it fresh. Now includes a real status section, a
  Mermaid diagram, the actual tech stack in use, working `curl` examples,
  and a documentation map.
- Started using memory (outside the project folder) to track deferred,
  explicitly-not-now optimizations the user asked to hold for a "final
  optimization pass": parallelizing hybrid search's two queries (separate
  `AsyncSession`s so they can run concurrently), an HNSW index for vector
  search, and a GIN index on a persisted `tsvector` column for keyword
  search.

### What I struggled with
- Asked a good question — "why do these run in parallel" — that
  contained a real premise error worth noting: they don't run in
  parallel at all, they run sequentially, on purpose. Landed once
  reframed with a "shared phone line" analogy for why one `AsyncSession`
  can't safely handle two queries at once.
- Was initially skeptical that keyword search added any value on top of
  vector search — a fair, common question, resolved with a concrete
  example (an exact error code a pure embedding match could plausibly
  miss).

### Concepts to revisit
- Where deferred optimizations get tracked is a bit split now: some live
  in `docs/PROGRESS.md` (this file, project history), some in Claude's
  own memory (cross-session, but outside the actual project folder,
  which caused real confusion this session about "where did that go").
  Worth keeping in mind: memory is a staging area until `/end-session`
  folds it in here — this file is the actual source of truth.

### What's next
- Reranking is next in the build order if we stick to the plan.
- Deferred to a future "optimization pass" (see memory,
  `future-optimizations.md`, and this entry above): parallelize hybrid
  search's two queries; add an HNSW index for vector search; add a GIN
  index on a persisted `tsvector` column for keyword search.
- Still no automated test suite — carried over multiple sessions, still
  the longest-standing open gap.
- PII detection, ACL, APIM, and Key Vault remain intentionally deferred
  per ADR-007.

---

## Session: 2026-08-05 — Documentation bar retrofit, code review, and hybrid search hardening

### What we built
- **Documentation Bar retrofit.** `CLAUDE.md` gained a new "Documentation
  Bar — Big Tech Interview Standard" section requiring `ARCHITECTURE.md`,
  `INTERVIEW_PREP.md`, and every ADR to show trade-offs, concrete
  scale/failure numbers, ownership-level (cost/operability/on-call)
  reasoning, and precision over vagueness. Applied it retroactively to
  all 11 existing ADRs (each gained a new "Scale, cost, and on-call
  reality" section) and threaded the same rigor into `ARCHITECTURE.md`
  and `INTERVIEW_PREP.md`'s existing sections. `README.md` was
  deliberately left alone — the new standard names only the three doc
  types above, and README's own job is quick external orientation, not
  interview-depth study material.
- **Ran `/code-review` on hybrid search.** A background review agent
  returned findings; each concrete one was re-verified directly against
  the live dev database (checked actual indexes with `\d chunks`,
  confirmed a claimed double `to_tsvector` computation with `EXPLAIN
  VERBOSE`, and disproved one claimed bug by just running the query it
  said would fail). Six findings survived verification. Two more
  suggestions (generalizing a two-argument function, deduplicating ~5
  lines across two methods) were deliberately dropped — both would have
  meant designing for hypothetical future need, which `CLAUDE.md`
  explicitly says not to do.
- **Fixed the most serious finding: a failure in either half of hybrid
  search took down the whole request**, even when the other half had
  good results. Fix: catch each search's failure independently, roll
  back the shared session so the other search can still run, and only
  raise (`RetrievalUnavailableError`, a new `503` in `app/api/query.py`)
  if *both* fail. Chose "proceed with what succeeded" over retrying, to
  avoid retry-storming an already-struggling database, and because
  Reciprocal Rank Fusion already treats a single-search result as fully
  legitimate.
- **Found and fixed a second bug the first fix introduced, only by
  testing it.** The `rollback()` needed to recover from one search's
  failure was expiring the *other*, already-successful search's fetched
  chunks (`Session.rollback()` invalidates every tracked object, not just
  the failed query's). Fixed by detaching each search's results from the
  session (`session.expunge()`) right after fetching them. Verified with
  a throwaway script that force-fails each search independently — this
  bug only showed up when the *first*-run search (vector) succeeded and
  the *second* (keyword) failed, not the reverse, since only already-
  loaded objects are vulnerable to being expired.
- Documented the decision and the subtlety in
  [`ADR-012`](adr/ADR-012-hybrid-search-partial-failure.md).
- Four remaining code-review findings (missing structured/correlation_id
  logging on the keyword-search error path, `to_tsvector` computed twice
  per row, hybrid search's RRF candidates truncated to `top_k` before
  merging — capping its own upside, `RRF_K` hardcoded instead of living
  in `Settings`) were deliberately deferred, tracked in a new memory file
  kept separate from the existing performance-optimization list, since
  the user wanted code-review-sourced fixes tracked apart from
  performance items.

### What I struggled with
- Skipped explaining back why the session-expiry bug only hit one
  direction (vector-succeeds-then-keyword-fails) and not the other — will
  revisit next session.
- Initially misread what "skip that call" meant in a walkthrough question
  about the rollback fix — worth double-checking my own phrasing is
  unambiguous before asking a check-back question.

### Concepts to revisit
- Why the session-expiry bug is direction-dependent (only the *first*
  search's results are at risk, since only already-loaded objects can be
  expired by a later rollback).
- SQLAlchemy's object expiration model in general — `expire_on_commit`
  only governs behavior after `commit()`, not `rollback()`, which always
  expires tracked objects unconditionally. Worth understanding this
  distinction cold, not just the one bug it caused here.

### What's next
- Four deferred code-review fixes tracked in memory
  (`code-review-followups.md`, kept separate from
  `future-optimizations.md`): structured logging on keyword-search
  errors, double `to_tsvector` computation, RRF candidate truncation
  before merge, and `RRF_K` moved into `Settings`.
- Performance items from last session remain deferred to the same future
  optimization pass: parallelizing hybrid search's two queries, HNSW
  index, GIN index.
- Reranking is still next in the build order if we stick to the plan.
- Still no automated test suite — this session's verification scripts
  were throwaway, not permanent; still the longest-standing open gap.
- PII detection, ACL, APIM, and Key Vault remain intentionally deferred
  per ADR-007.

---

## Session: 2026-08-05 (continued) — Test suite (started, paused), Feature 4: Reranking

### What we built
- **Started the automated test suite, then deliberately paused it.**
  Added `pytest`/`pytest-asyncio`, fixed the same "no module named app"
  issue `create_tables.py` has via `pythonpath = ["."]` in
  `pyproject.toml`. Wrote and verified `tests/test_chunking.py` (5 tests)
  and `tests/test_extraction.py` (4 tests, faking `pypdf.PdfReader` since
  testing a third-party library's own parsing isn't our job). Agreed on a
  real-database/faked-OpenAI testing strategy — proven correct in the
  same conversation, since last session's real bugs were only catchable
  against a real database. Paused by explicit choice to move to
  reranking; remaining work (a test database fixture, the ingestion
  integration test, and tests for hybrid search, the ADR-012 fallback,
  the circuit breaker, and the audit log) is tracked in memory
  (`test-suite-progress.md`), not forgotten.
- **Built reranking (Feature 4).** Compared three options — a local
  Hugging Face cross-encoder, Voyage AI's hosted Rerank API, and
  prompt-based reranking via OpenAI — and chose Voyage specifically to
  use a model actually trained for relevance scoring, without pulling a
  heavy new ML dependency into a project that otherwise only talks to
  hosted AI APIs. Both searches (and RRF's own merge) now fetch a wider
  pool of 20 candidates instead of 5, and a new
  `app/services/reranking.py` narrows that pool to the final 5 using
  Voyage's `rerank-2.5-lite` model, wrapped in its own circuit breaker.
  If Voyage fails, `retrieval_service.py` falls back to hybrid search's
  own RRF order rather than failing the request — verified for real by
  forcing the circuit breaker open. This also fixed a previously-deferred
  code-review finding as a side effect: RRF used to be capped at
  `retrieval_top_k` before merging, so it could never reward a chunk both
  searches ranked just outside that cutoff.
- Documented the decision in
  [`ADR-013`](adr/ADR-013-reranking-with-voyage-ai.md), including the
  secret-handling mistake below, honestly, as part of the record.

### What I struggled with
- Understood the core trade-off (narrow tests localize failures) well on
  the first try. Needed one correction on reranking: initially thought
  reranking's role was to hand the LLM each chunk's "priority" to weigh
  during generation — the LLM never sees scores at all; reranking only
  decides *which* chunks reach the LLM in the first place.
- A real incident: pasted the real Voyage API key into `.env.example`
  (the tracked template file) instead of `.env` (git-ignored). Caught
  immediately — confirmed via `git status`/`git log` that nothing had
  been committed or pushed — fixed in place, and rotated the key anyway
  since it had already appeared in conversation text. Worth remembering
  going forward: `.env.example` only ever gets placeholder values.

### Concepts to revisit
- Why patching `pypdf.PdfReader` directly (instead of
  `app.services.extraction.PdfReader`, where the name is actually looked
  up) wouldn't have worked — asked, not yet answered back.
- Why the session-expiry bug from last session was direction-dependent —
  carried over from last session, still not revisited.

### What's next
- Resume the paused test suite: a dedicated test database, the ingestion
  integration test, then hybrid search, the ADR-012 fallback, the circuit
  breaker, and the audit log (see `test-suite-progress.md` in memory for
  the full list).
- Four code-review-sourced fixes and the earlier performance items
  remain deferred, tracked in memory
  (`code-review-followups.md`, `future-optimizations.md`).
- LangGraph multi-step query pipeline is next in the build order after
  reranking, if we stick to the plan.
- PII detection, ACL, APIM, and Key Vault remain intentionally deferred
  per ADR-007.
