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

---

## Session: 2026-08-06 — Test suite resumed, Feature 5: LangGraph query pipeline

### What we built
- **Test suite resumed and the paused work finished.** Added
  `tests/conftest.py`: a dedicated test database (same host/credentials
  as dev, different database name), a session-scoped fixture creating
  every table once and dropping them all when the run ends, and a
  `db_session` fixture that wipes every table after each test (a plain
  `rollback()` isn't enough, since the repository commits on its own —
  the data is already persisted by the time a test ends). Hit and fixed
  a real async-testing gotcha: the test engine needed `NullPool`, since
  pytest-asyncio gives each test function its own event loop, and a
  pooled connection tied to one loop breaks under a different test's
  loop. Wrote `tests/test_ingestion_service.py` (2 tests: success path,
  failure path correctly marks a document `failed`) — all 11 tests
  (chunking, extraction, ingestion) pass.
- **Built the LangGraph query pipeline (Feature 5).** New
  `app/services/query_rewriting.py` (an isolated LLM call with its own
  circuit breaker) and `app/services/query_graph.py` (the `QueryState`
  shape and the compiled graph). `RetrievalService.answer_question` now
  builds and runs a graph instead of a fixed sequence; the actual step
  logic moved into five methods on the class, all reusing the exact same
  hardened search/rerank helpers from ADR-012/ADR-013 unchanged.
- **The original architecture's retry trigger ("zero chunks returned")
  was built, tested live, and found not to work** — vector search has no
  relevance floor, so it always returns *something*, however irrelevant.
  Pivoted to Voyage's own `relevance_score` on the best reranked chunk,
  thresholded at `0.4` — a number picked empirically from real measured
  scores (`0.914` for a true match, `~0.28–0.29` for two different
  irrelevant questions against the same data), not guessed.
- Made the retry skip entirely, not just decline, when reranking itself
  is unavailable (as opposed to merely weak) — a real design refinement
  contributed by explaining *why* during the session: rewriting the
  question can't fix an unreachable vendor API.
- Verified live and via targeted mocking: a relevant question (no
  retry), an irrelevant question (retry actually fires now, unlike the
  original empty-check version), a reranker-circuit-open case (retry
  correctly skipped), and a rewrite-circuit-open case mid-retry (loop
  terminates in exactly 2 attempts, still produces an answer). Found and
  fixed a real testing mistake along the way: patching
  `RetrievalService._rewrite_node` on the class after constructing the
  service silently did nothing, since the graph captures a bound-method
  reference at `__init__` time — fixed by patching the module-level
  `rewrite_query` function instead.
- Documented the full decision, including the failed first attempt, in
  [`ADR-014`](adr/ADR-014-langgraph-query-pipeline.md).
- `CLAUDE.md`'s build order gained a new item 15: LLM/RAG-specific
  observability (tracing prompts, retrieved context, token cost, and
  per-call latency — distinct from the general infra monitoring already
  planned), candidates to evaluate being LangSmith and Langfuse.

### What I struggled with
- Initially proposed raising `MAX_RETRIES` to handle 10x traffic — a
  reasonable-sounding instinct that's actually backwards, since more
  retries under load means more calls to the exact vendors already
  struggling. Corrected by tracing through the actual amplification and
  connecting it back to ADR-012's already-established retry-storm
  reasoning.
- Repeated a deliberately planted false claim twice (that a
  circuit-open reranking fallback assigns a relevance score of `1.0`)
  before catching it on the third pass, once shown the literal code —
  the real value is `0.0`, and the `reranker_unavailable` flag, not the
  score, is what actually prevents the retry.
- Gave real, independent insight once past that: correctly reasoned
  that skipping the retry on a reranker outage isn't about cost or
  "compounding degraded paths" (the reasoning initially offered) but
  about the same circuit breaker very likely still being open a moment
  later — a sharper answer than the one given.

### Concepts to revisit
- Why patching `pypdf.PdfReader` directly (instead of
  `app.services.extraction.PdfReader`) wouldn't have worked — asked
  multiple sessions ago, still not answered back.
- Why the session-expiry bug from the hybrid-search hardening session
  was direction-dependent — still carried over, still not revisited.

### What's next
- Neo4j document relationship graph is next in the build order if we
  stick to the plan.
- The test suite still has real gaps: hybrid search, the ADR-012
  fallback, the circuit breaker's state transitions, the audit log's
  insert-only behavior, and now the query graph's own retry logic —
  today only verified with throwaway scripts, not permanent tests.
- Re-tune `retrieval_relevance_threshold` (currently `0.4`) once there
  are real, topically-varied documents — it was picked from only two
  data points against a 4-chunk database (see `future-optimizations.md`
  in memory).
- Four code-review-sourced fixes and the earlier performance items
  remain deferred (`code-review-followups.md`, `future-optimizations.md`).
- PII detection, ACL, APIM, and Key Vault remain intentionally deferred
  per ADR-007.

**Estimated completion: ~18% of the total project, by weighted effort**
— not a flat step count. 5 of 15 build-order items are done (plus the
cross-cutting correlation ID/audit/circuit-breaker work), but the two
largest remaining chunks — the polished production frontend (5 pages,
Shadcn, responsive, dark mode) and full Azure deployment (Terraform for
every service, GitHub Actions CI/CD) — haven't been started at all, and
together likely outweigh everything built so far combined. Rough
remaining effort: ~100 hours across the test suite, Neo4j, PII
detection, ACL, the evaluation harness, the MCP server, API Management,
Azure deployment, the frontend, and auth/multi-tenancy hardening. At
3–4 hours/day, that's roughly 28–30 working days left, assuming no
scope changes — a real estimate, not a target.

---

## Session: 2026-08-06 (continued) — Feature 6: Neo4j document relationship graph

### What we built
- **Neo4j document relationship graph, built and verified live.** Added
  Neo4j to `docker-compose.yml`, `app/core/graph_database.py` (driver
  setup, mirrors `database.py`), and `app/repositories/graph_repository.py`
  (all Cypher access, own circuit breaker `neo4j`). The relationship
  type was a real design decision, not assumed: rejected "topic
  clusters an LLM infers" as the primary strategy, specifically because
  it would substantially duplicate what vector search already does;
  landed on explicit references extracted from a document's own text
  instead, since that's the one thing similarity search structurally
  can't do.
- **Reference extraction + resolution, reusing existing infrastructure.**
  New `app/services/reference_extraction.py` (an LLM call, own circuit
  breaker `openai_reference_extraction`) pulls specific named mentions
  out of a document's text. Resolving each mention to a real document
  reuses `find_by_keyword` directly — no new search mechanism needed.
  New `app/services/document_graph_service.py` orchestrates
  extract → resolve → write (`MERGE`, not `CREATE`, so re-processing a
  document is idempotent), filtering out self-references, since a
  document's own text usually contains whatever it mentions.
- **Wired into both existing pipelines.** `app/api/documents.py` runs
  reference-building right after a document is marked `ready` —
  best-effort: only `CircuitOpenError` is caught, so the upload still
  succeeds if Neo4j or extraction is unavailable. `retrieval_service.py`
  gained a sixth graph node, `_graph_context_node`, inserted between
  "decided to generate" and actually generating: for the documents
  behind the final reranked chunks, it asks Neo4j what each directly
  references (one hop only) and pulls one representative snippet
  (`document_repository.py`'s new `get_first_chunk_text`) from each.
- **Verified live, meaningfully, not just that it runs.** Ingested two
  real documents where one's text named a ticket ID the other actually
  defined; confirmed the edge got written; then asked a question
  answerable only by combining both documents, and the answer correctly
  cited the detail that existed solely in the graph-linked document, not
  the directly-retrieved one.
- Documented the full decision, including the rejected topic-cluster
  option and why, in [`ADR-015`](adr/ADR-015-neo4j-document-relationship-graph.md).

### What I struggled with
- Proposed topic-cluster/LLM-inferred linking as the primary strategy
  before the alternative was discussed — a reasonable-sounding idea that
  turned out to substantially overlap with existing vector search
  capability. Landed cleanly on the sharper distinction (explicit
  structural links vs. re-implemented similarity) once it was named.
- Twice described `_graph_context_node`'s mechanics with real
  imprecision: framed it as sending data *to* `retrieval_service`
  rather than being *part of* it, and separately described the wrong
  role of the `set` used to dedupe source documents (thought it was the
  return value; it's only used going into the loop).
- Missed, then repeated as true, a deliberately planted claim that a
  failed *read-only* query wouldn't need a `rollback()` — a direct
  extension of the ADR-012 lesson to genuinely new code, not just the
  original bug site. Landed only after a second, differently-framed
  explanation (the "jammed printer" analogy), and correctly reasoned
  through the concrete consequence unprompted once it clicked: a failed
  snippet lookup would cascade and break the *next* one in the same
  loop, not because of a real problem with that document, but because
  the session itself would still be stuck.
- Caught a separate planted error cleanly, without help: correctly held
  that Cypher's `->` arrow really does restrict relationship direction,
  directly contradicting an authoritative-sounding false claim stated
  moments earlier.

### Concepts to revisit
- Why patching `pypdf.PdfReader` directly wouldn't have worked — still
  carried over, still not answered back, several sessions running now.
- Why the hybrid-search session-expiry bug was direction-dependent —
  same, still carried over.

### What's next
- The pending explain-back question from this chunk (what
  `_graph_context_node` does, in full) was deferred to next session by
  explicit choice, to run `/end-session` first — pick that back up
  before moving on to new work.
- Neo4j's own index gap (`MATCH (d:Document {id: ...})` scans, doesn't
  index) is now tracked alongside pgvector's HNSW and full-text's GIN
  gaps — same shape of deferred work, one more entry on the list.
- PII detection is next in the build order if we stick to the plan —
  and per last session's pushback discussion, still the stronger
  candidate over frontend/deployment, since ACL and PII are the two
  items with concrete (not just build-order-says-so) reasons to do them
  first: cost/security exposure if deployed without auth, and frontend
  pages that need data (PII badges, ACL settings) that don't exist yet.
- The test suite still hasn't grown since the ingestion tests — hybrid
  search, ADR-012's fallback, the circuit breaker, the audit log, the
  LangGraph retry logic, and now the graph feature are all still
  untested beyond throwaway verification scripts.
- Four code-review-sourced fixes and earlier performance items remain
  deferred (`code-review-followups.md`, `future-optimizations.md`),
  now joined by the Neo4j relevance-threshold-style item: the naive
  "first chunk" snippet selection for referenced documents, a known
  simplification worth revisiting once there's real document variety.

**Estimated completion: ~21% of the total project, by weighted effort**
— up from ~18% last session. 6 of 15 build-order items are done, but
the estimate moves less than the step count suggests, since the two
largest remaining chunks (the frontend and full Azure deployment)
still haven't been touched. Rough remaining effort: ~93 hours across
the test suite, PII detection, ACL, the evaluation harness, the MCP
server, API Management, Azure deployment, the frontend, and
auth/multi-tenancy hardening. At 3–4 hours/day, that's roughly 24–26
working days left, assuming no scope changes.

---

## Session: 2026-08-07 — New build-order item (guardrails), Feature 7: Evaluation harness

### What we built
- **Clarified and split a conflated feature request.** "Evaluate the
  answer for ethics/security/guardrails before showing it to the user"
  turned out to be two genuinely different things: a real-time safety
  gate on every live answer (new build-order item 16, deliberately
  placed last — no real exposure to protect against yet, since nothing
  is deployed with real external users, but good, distinctive interview
  material), and the already-planned offline evaluation harness (item
  9, built this session). Conflating them would have meant building the
  wrong shape of tool.
- **Evaluation harness, built and verified live.** New top-level `eval/`
  directory: `eval/fixtures/` (three small, purpose-written, topically
  distinct documents), `eval/dataset.json` (six test cases), `eval/judge.py`
  (two separate LLM-as-judge functions — faithfulness and correctness —
  own circuit breaker `openai_eval_judge`, both fail closed: default to
  `False`, not `True`, on a missing key or unparseable response), and
  `eval/run_eval.py` (the runner). Two small, genuinely reusable
  additions to existing files: `DocumentRepository.get_document_by_filename`
  (idempotent fixture lookup) and `RetrievalService.run_query` (returns
  the full pipeline state, not just the answer — `answer_question` is
  now a thin wrapper around it).
- **A real design correction mid-session:** initially misdescribed the
  fixture-isolation approach as "a separate database," which isn't what
  got built — it's dedicated fixture *documents* in the *same* database
  as everything else, idempotently ingested. Caught and corrected before
  writing the ADR, not after.
- **Verified live, fully:** all 6 test cases passed on all three
  dimensions — retrieval, faithfulness, correctness — against the real
  pipeline, real Postgres, real Neo4j, real OpenAI, and real Voyage.
  Also hit Voyage's real 3-requests-per-minute free-tier limit running
  all 6 cases back to back — this time inside a permanent feature, not
  a throwaway script, so it was actually fixed with a paced 20-second
  delay between cases (skipped before the first, so a single-case run
  isn't needlessly slowed).
- Documented the decision, including the rejected "separate database"
  framing and the honest LLM-as-judge limitation, in
  [`ADR-016`](adr/ADR-016-llm-judge-evaluation-harness.md).
- Also resolved an old, still-open loop from two sessions back: gave a
  full, correct explanation of `_graph_context_node` and `build_references`,
  including catching two separate planted errors cleanly (Cypher's `->`
  really does restrict direction; `next()` correctly skips self-references
  rather than giving up on the first match) after initially missing or
  repeating a couple of others (the reranker-fallback score, and whether
  a failed read-only query still needs a rollback).

### What I struggled with
- Needed two passes to land why a failed *read-only* query still needs
  `rollback()` — reused a planted claim from ADR-012 almost verbatim
  before catching it on the third attempt, once shown the literal code
  and a "jammed printer" analogy instead of the same explanation
  repeated.
- Initially proposed raising `MAX_RETRIES` for 10x traffic — corrected
  in the same exchange by tracing through the actual amplification.
  Later, independently and correctly identified a real, separate gap
  while discussing that same topic: the circuit breaker's own
  `_record_success()` clears its failure count on *any* success, so it
  effectively requires *consecutive* failures to trip, not "N failures
  in a window" as its own docstring claims — a genuine, previously
  unnoticed correctness bug, tracked in `code-review-followups.md`.
- Conflated real-time guardrails with the offline evaluation harness at
  first — resolved cleanly once the distinction (per-request gate vs.
  batch quality report) was named directly.

### Concepts to revisit
- Why patching `pypdf.PdfReader` directly wouldn't have worked — still
  unanswered, now several sessions running.
- The circuit breaker's consecutive-vs-windowed failure counting gap
  (see above) — understood *that* it's wrong, not yet whether the fix
  (track a rolling window of outcomes, not just clear on success) has
  any subtleties of its own.

### What's next
- The circuit breaker correctness bug found this session is now tracked
  in `code-review-followups.md` alongside the other deferred fixes —
  worth prioritizing before this project ever runs under real
  concurrent load, since it means the breaker may never trip for a
  genuinely degraded (not fully down) vendor.
- Real-time answer guardrails (build-order item 16) is deliberately
  deferred to the end — tracked, not forgotten.
- The evaluation harness isn't wired into CI yet — still a fully manual,
  on-demand tool. Wiring it into GitHub Actions is natural future work,
  likely alongside build-order item 12 (Azure deployment + CI/CD).
- PII detection (item 7) is next in the build order if we stick to the
  plan — deliberately skipped ahead of again this session (eval harness
  before PII/ACL) for a reasoned, not arbitrary, reason: the retrieval
  pipeline's growing complexity made systematic quality measurement
  more urgent than a compliance feature with no live exposure yet.
- The test suite still hasn't grown since the ingestion tests — hybrid
  search, ADR-012's fallback, the circuit breaker, the audit log, the
  LangGraph retry logic, and the graph feature remain untested beyond
  throwaway verification scripts and the new eval harness (which is a
  quality measure, not a correctness test suite).

**Estimated completion: ~27% of the total project, by weighted effort**
— up from ~21% last session. 7 of 15 build-order items are done (plus
one new item added to the list, 16). Rough remaining effort: ~86 hours
across the test suite, PII detection, ACL, the MCP server, API
Management, Azure deployment, the frontend, and auth/multi-tenancy
hardening — the frontend and Azure deployment remain the two largest
untouched chunks. At 3–4 hours/day, that's roughly 24–25 working days
left, assuming no scope changes.

---

## Session: 2026-08-07 (continued) — Feature 8: MCP server

### What we built
- **MCP server, build-order item 10.** Exposes the pipeline as two
  tools other AI clients can call directly: `ask_knowledge_base` and
  `upload_document`. New files: `app/mcp/auth.py` (`ApiKeyMiddleware`),
  `app/mcp/server.py` (the two tools), one new setting (`mcp_api_key`),
  and `main.py` wiring (a `lifespan` context manager plus the `/mcp`
  mount). New dependency: the official `mcp` Python SDK.
- **A real scope decision, made explicitly, not defaulted into:** chose
  a network-reachable HTTP server over a local-only one, specifically
  to learn how this pattern works in a real enterprise deployment. That
  choice reopened the PII/ACL-ordering question from earlier sessions —
  resolved by pulling forward a *minimal* slice of build-order item 14
  (one shared API key, checked with a constant-time comparison) rather
  than building full auth, and rather than reverting to local.
- **Zero changes needed to `IngestionService`, `DocumentGraphService`,
  or `RetrievalService`** to support the new entry point — confirmed
  live as a direct consequence of those services never having imported
  anything FastAPI-specific in the first place.
- **Found and fixed two real bugs, live, not by reading the code:**
  (1) `app.mount()` doesn't forward FastAPI's startup event into a
  mounted sub-app, so the MCP session manager's task group was never
  initialized — every request failed with `RuntimeError: Task group is
  not initialized` even past a correct API key. Fixed with an explicit
  `lifespan` context manager entering `mcp.session_manager.run()`.
  (2) Starlette's `BaseHTTPMiddleware` runs the wrapped app in a
  separate, buffered task, which silently breaks MCP's long-lived
  streaming responses — the real key still failed with "SSE stream
  ended without a response." Fixed by writing the API key gate as raw
  ASGI middleware instead.
- **Found and fixed a real correctness gap** in the new `upload_document`
  tool: its audit log write, copied from `documents.py`'s existing
  pattern, sat *after* the best-effort graph-linking step — so an
  unexpected (non-`CircuitOpenError`) failure there would leave a
  successfully ingested document with no audit trail at all. Fixed here
  by moving the audit log write to right after ingestion succeeds. The
  identical gap still exists in `documents.py` itself — tracked in
  `code-review-followups.md`, not fixed this session, per explicit
  instruction to fix only the new code.
- **Verified fully live**, through the real MCP protocol, not an
  in-process call: a throwaway client script confirmed a missing key
  and a wrong key both get rejected with a real 401, and a request with
  the correct key can list both tools, upload a test document, and get
  back a grounded answer citing content from that same upload.
- Documented in [`ADR-017`](adr/ADR-017-mcp-server.md).

### What I struggled with
- Missed the planted claim that a missing required setting would "fail
  safe" quietly at request time — the real behavior is a loud failure
  at app startup, before any request is ever served. Caught cleanly
  once shown the "restaurant that never opens its doors" analogy.
- Missed the planted claim about a race condition in correlation ID
  handling across concurrent requests — `ContextVar` gives every
  request its own isolated copy, no shared state to race over. Caught
  cleanly once shown the "private notebook page" analogy.
- Missed the planted claim about middleware registration order
  affecting which routes get a correlation ID — first asked to skip
  the question outright, which was correctly declined per this
  project's own rule ("never move to the next chunk until I've
  demonstrated understanding"); answered correctly once the question
  was simplified to a plain yes/no.
- The connect-the-dots question on *why* the existing services could be
  reused completely unchanged initially got a circular answer ("because
  we routed MCP through the same path") before landing on the real
  reason: those services never depended on FastAPI to begin with.
- Correctly caught, on the first attempt, that a narrow
  `except CircuitOpenError` would *not* also catch an unrelated error
  like a corrupted PDF — a genuinely sharp catch, no correction needed.

### Concepts to revisit
- Why patching `pypdf.PdfReader` directly wouldn't have worked — still
  unanswered, now several sessions running.
- How a leaked `MCP_API_KEY` would actually be detected — correctly
  named today as a real, currently-unsolved gap (no anomaly detection
  exists yet), not a misunderstanding to correct, but worth returning
  to once build-order item 14 exists for real.

### What's next
- **Explicitly deferred by request**, not forgotten: automated tests
  for the MCP server. Everything so far was verified with a throwaway
  script, not a permanent test.
- The `documents.py` audit-log-ordering gap (same shape as the one just
  fixed in the MCP tool) is tracked in `code-review-followups.md`,
  still not fixed.
- The circuit breaker consecutive-failures bug remains deferred,
  unchanged from last session.
- PII detection (item 7) and ACL (item 8) remain the next items in
  build order if followed strictly — skipped again this session in
  favor of MCP, for a reasoned trade-off (a minimal auth slice was
  enough to make HTTP exposure acceptable) rather than an oversight.
- The test suite still hasn't grown beyond ingestion tests — now also
  missing MCP coverage on top of hybrid search, the circuit breaker,
  the audit log, LangGraph retries, and the graph feature.

**Estimated completion: ~32% of the total project, by weighted effort**
— up from ~27% last session. 8 of 16 build-order items are done. The
jump is larger than a flat 1-of-16 share because MCP reused nearly
everything already built rather than adding a new dependency surface —
but the frontend and Azure deployment remain the two largest untouched
chunks, so the percentage still moves conservatively. Rough remaining
effort: ~80 hours across the test suite, PII detection, ACL, real
auth/multi-tenancy (item 14 — only a small slice of it exists so far),
API Management, Azure deployment, the frontend, and guardrails (item
16). At 3–4 hours/day, that's roughly 20–27 working days left, assuming
no scope changes.

---

## Session: 2026-08-07 (continued) — Interview prep document: flowcharts added to earlier features

### What we built
- No new code and no new build-order item — a documentation-only pass.
  `INTERVIEW_PREP.md`'s "each feature section needs its own flowchart"
  rule was added mid-project and only applied going forward, so
  Features 7 (evaluation harness) and 8 (MCP server) got one but
  Features 1–6, plus the two unnumbered enterprise-requirement
  sections (Correlation IDs/Audit Logging/Circuit Breakers, and Hybrid
  Search Hardening), didn't. Retrofitted all eight of those older
  sections with a Mermaid flowchart, placed in the same spot as
  Features 7/8's — right after the one-sentence "what does this do"
  answer, before the rest of the Q&A. No existing text changed, only
  diagrams added.
- Each flowchart is specific to that feature's own flow (e.g. the
  ingestion one shows extract → chunk → embed-as-one-batch →
  save-or-fail; the LangGraph one shows the relevance-score branch
  back to question-rewrite), not a copy of the system-wide diagram
  already in `ARCHITECTURE.md`.

### What I struggled with
Not applicable this session — no Step 4 code walkthrough happened, so
no planted-error question was asked.

### Concepts to revisit
Unchanged from last session — see above.

### What's next
Unchanged from last session: PII detection (item 7) and ACL (item 8)
remain the next build-order items if followed strictly; the MCP test
suite, the `documents.py` audit-log-ordering gap, and the circuit
breaker consecutive-failures bug are all still open.

**Estimated completion: ~32% of the total project, by weighted effort**
— unchanged from last session. This was a documentation-quality pass,
not a build-order item, so it doesn't move the percentage. 8 of 16
build-order items are done. Remaining effort is still roughly ~80
hours across the test suite, PII detection, ACL, real auth/multi-
tenancy (item 14), API Management, Azure deployment, the frontend, and
guardrails (item 16). At 3–4 hours/day, that's still roughly 20–27
working days left, assuming no scope changes.

---

## Session: 2026-08-08 — Feature 9: PII detection

### What we built
- **PII detection, build-order item 7**, motivated by a concrete
  reason rather than just "it's next": last session's MCP server made
  `upload_document` a real, network-reachable way for someone else's
  data to enter the system, turning this from a theoretical compliance
  concern into an actual exposure. Runs inside `IngestionService`, not
  either API route, so it protects `/documents/upload` and MCP's
  `upload_document` automatically — verified live through both paths,
  including a document containing an Indian PAN number uploaded
  specifically through MCP.
- **New Azure dependency, the first real one this project has needed** —
  `app/services/pii_detection.py`, calling Azure AI Language via its
  own dedicated circuit breaker (`azure_pii_detection`), independent
  from every other one in this project.
- **Two real things found only by live testing, not code review:**
  (1) Azure's `PersonType` category flagged ordinary words like
  "employee" as PII at 98% confidence — not even in Azure's own list
  of categories that can be explicitly excluded by name. Fixed with an
  explicit 14-category allowlist (names, contact info, financial data,
  US and India government IDs) instead of Azure's full 173-category
  default set. (2) Azure's real synchronous-request limit — 5,120
  characters per document, 5 documents per request — verified against
  Microsoft's own docs rather than assumed, and handled by splitting
  long text on paragraph breaks (not a hard character cut) and
  batching pieces.
- **Schema changes, with two genuine gotchas caught before they broke
  anything:** new `DocumentStatus.PENDING_REVIEW`, and `pii_detected`/
  `failure_reason` columns on `Document`. Checking the live database
  directly (not assuming) showed SQLAlchemy's native Postgres enum
  stores the Python enum's *member names* (`PENDING`, `READY`), not
  its lowercase `.value` strings — the `ALTER TYPE` command needed
  `'PENDING_REVIEW'`, not `'pending_review'`. Separately, SQLAlchemy's
  `default=` is Python-side only; the `pii_detected` column's
  `ALTER TABLE` needed its own SQL-level `DEFAULT false` to apply to
  rows that already existed, not just future ones — caught as a
  planted-error explain-back the user missed on the first pass, then
  correctly explained back once shown the "restaurant that never opens
  its doors" framing.
- **A mid-build scope addition, requested directly, not planned:**
  `failure_reason`, recording *why* a document failed (an extraction
  bug vs. an Azure outage previously both collapsed into the same
  generic `failed` status with no way to tell them apart) — the user
  asked for this the moment the ambiguity became visible during a
  planted-error explain-back, and it was built immediately, not
  deferred.
- **Fail closed, not fail open, on an Azure outage** — a deliberate
  departure from this project's usual best-effort pattern (reranking,
  Neo4j), since this is a compliance gate: an unverified document must
  not be embedded. Notably, this decision needed no new code — `CircuitOpenError`
  already flows into the existing generic failure-handling path once
  the check was placed inside the same `try` block as everything else.
- **Real test coverage added, and a real gap found while adding it:**
  the two existing ingestion tests didn't mock the new `detect_pii`
  call at all, meaning they'd been silently hitting the real Azure API
  on every run since it was wired in. Fixed alongside adding a new
  test for the PII-found branch, which asserts `embed_chunks` was
  never called — not just that zero chunks got saved — since calling
  it at all would mean PII-containing text already left the system for
  a third-party vendor, regardless of what happened to the result
  afterward.
- Documented in [`ADR-018`](adr/ADR-018-pii-detection.md).

### What I struggled with
- Missed two planted-error explain-backs this session: the
  `default=`-doesn't-retroactively-apply-to-existing-rows claim (caught
  on request for a simplified yes/no version), and a claim about
  `documentstatus` naming (this one was caught correctly). Correctly
  caught, without missing, the `except CircuitOpenError` specificity
  question and the "circuit breaker records 3 failures for 3 unattempted
  batches" claim.
- Tried to skip an explain-back question outright once ("I would skip
  this question") — correctly declined per this project's own rule,
  resolved once simplified to a plain yes/no.
- After the feature was fully built and verified, raised a genuine,
  unprompted reconsideration of the fail-closed decision — not a
  misunderstanding to correct, a real architectural pushback (one
  vendor outage blocking all uploads is a real availability cost). Not
  changed now; tracked to revisit once real traffic exists, alongside
  a related but distinct gap surfaced in the same discussion: no admin
  UI or alerting yet for a growing `PENDING_REVIEW` backlog.

### Concepts to revisit
- Why patching `pypdf.PdfReader` directly wouldn't have worked — still
  unanswered, many sessions running now.
- Whether the fail-closed decision should change once this handles
  real traffic — an open reconsideration, not a settled question,
  tracked in memory (`deferred-design-decisions.md`).

### What's next
- ACL (build-order item 8) is next if the build order is followed
  strictly — PII detection was this session's item 7.
- The PII allowlist only covers US and India identity formats today —
  a deliberate, named scope limit, not comprehensive coverage.
- No automated tests yet for `_split_into_documents`'s paragraph
  splitting logic, the category-filtering behavior itself, or the
  fail-closed circuit-breaker-open path — only the "PII found, stop
  before embedding" branch got a test this session, by explicit
  request ("build one or two test cases... leave rest for future").
- Still open, unchanged from before: the `documents.py`
  audit-log-ordering gap, the circuit breaker consecutive-failures
  bug, and MCP-specific automated tests.
- `test-suite-progress.md` (memory) was found stale this session —
  it described `conftest.py` and `test_ingestion_service.py` as "not
  yet built," when both had actually been completed in an earlier
  session. Corrected by checking the real file state directly rather
  than trusting the memory.

**Estimated completion: ~40% of the total project, by weighted effort**
— up from ~32% last session. 9 of 16 build-order items are done. The
jump reflects a genuinely substantial feature — a new external
dependency, real schema changes, two live-testing-driven pivots, and
test coverage — not just a checklist item. Rough remaining effort:
~70 hours across the test suite, ACL, real auth/multi-tenancy (item
14), API Management, Azure deployment, the frontend, and guardrails
(item 16) — the frontend and Azure deployment remain the two largest
untouched chunks. At 3–4 hours/day, that's roughly 18–24 working days
left, assuming no scope changes.

---

## Session: 2026-08-09 — Feature 10: Document-level access control

### What we built
- **Document-level access control, build-order item 8**, motivated the
  same concrete way PII detection was: with MCP and the REST endpoint
  both live, uploaded documents are genuinely confidential material
  with nothing yet restricting who could retrieve them. Chose to solve
  the "no user model exists yet" prerequisite gap the same way MCP
  solved its own auth gap last month — a lightweight `user_id` stand-in
  built as the first chunk of this feature itself, not as separate,
  deferred prerequisite work.
- **Identity middleware** (`app/core/middleware.py`), mirroring
  `correlation_id_middleware`'s `ContextVar` pattern exactly, chosen
  specifically because it needed to cover MCP too, and MCP tools can't
  use FastAPI's route-level `Depends()`. A missing `X-User-Id` header
  is rejected outright with a 401 — unlike a correlation ID, an
  identity can't be safely invented. `/docs`, `/openapi.json`, and
  `/redoc` stay exempt so Swagger UI remains browsable.
- **Found live: FastAPI's middleware order is reversed from the
  intuitive reading** — the *last*-registered middleware ends up
  *outermost*. `correlation_id_middleware` had to move to last, not
  first, so it still wraps and stamps a header even on a 401
  rejection, closing a gap where rejected requests briefly had no
  correlation ID at all — a direct violation of `CLAUDE.md`'s own
  "every response includes one" rule.
- **A scope addition raised mid-session, not originally planned:**
  rejected requests now get their own audit log entry
  (`action="access_denied"`), after directly weighing whether "nothing
  happened, so nothing to log" was the right call for a
  security-relevant rejection versus a routine business action.
- **The audit log's `user_id` column — present since `ADR-008`, never
  once populated** — is now filled in on every `document_upload`,
  `query_made`, and the new `permission_granted` action.
- **`document_permissions` table + repository**: one row per
  (document, user) grant, `grant_access` idempotent via
  `ON CONFLICT DO NOTHING` (not check-then-insert, to avoid a race
  between two concurrent grants), `has_access` a plain existence
  check. Uploading a document auto-grants the uploader, unconditionally,
  *before* the ingestion `try` block — survives regardless of whether
  the document ends up ready, failed, or pending review.
- **A new sharing endpoint**, `POST /documents/{id}/access` — the
  simplest available rule chosen deliberately: anyone who currently
  has access can grant it to someone else, not only the original
  uploader, since the permissions table has no ownership concept to
  fall back to. Accepted as a real, named scope trade-off, not an
  oversight.
- **The actual enforcement**: `find_similar_chunks` and `find_by_keyword`
  now join against `document_permissions`, filtered *before* the
  ranking and the `LIMIT` — the same reasoning `ADR-012` already used
  to avoid silently truncating results by filtering too late.
- **Two real bugs found live, both from the same root cause** — a new
  permission check protects exactly the function it was added to nothing
  else that happens to read the same data: (1) `DocumentGraphService.build_references`
  crashed against the newly-required parameter; fixed with a
  deliberately separate, permission-agnostic `find_by_keyword_unrestricted`,
  since reference-graph-building is a system-wide fact about documents,
  not a user-scoped retrieval. (2) **A real security gap** —
  `get_first_chunk_text`, the function behind graph-context snippets,
  had *no permission check at all*. A user could receive content from
  a document they were never granted access to, as long as some
  document they could see happened to reference it. Neither bug was
  visible from reading `_retrieve_node` alone; both surfaced only once
  the feature was exercised end to end.
- **Verified live, fully, through every path**: a document owner gets
  a correct answer; a second user with no grant gets "I don't know"
  for the identical question; granting access makes the same question
  succeed immediately after; every document uploaded before this
  feature existed is now correctly invisible to everyone, including
  its own uploader, until re-granted — a consequence flagged and
  predicted before it was ever observed, not a surprise afterward.
- Documented in [`ADR-019`](adr/ADR-019-document-level-access-control.md).

### What I struggled with
- Missed one planted-error explain-back this session (the `/mcp`
  exemption claim — whether `PUBLIC_PATHS` accidentally covered MCP
  too), corrected cleanly on request. Correctly caught several others
  without missing: the `ON CONFLICT DO NOTHING`-versus-`has_access`
  enforcement question, the `_rewrite_node`/retry-loop state-merging
  question (twice, once abstractly and once when asked to restate it
  concretely), and the audit-log validation-error claim.
- One explain-back answer needed re-explaining in more concrete,
  step-by-step terms (SQL as a single declarative condition versus a
  procedural loop) before it landed — the librarian/keycard analogy
  worked where the first, more abstract phrasing hadn't.
- Briefly asked to stop mid-explanation; resumed a short while later
  with a clarifying question instead of the original explain-back,
  which was answered directly rather than re-pushed.
- After the feature was fully built and verified, correctly identified
  from memory (unprompted) that `_rewrite_node`'s partial-dict return
  meant `user_id` survives a retry unchanged — a right answer to a
  question that hadn't been asked yet, showing real internalization of
  how LangGraph state merging works, not just this feature's specifics.

### Concepts to revisit
- Why patching `pypdf.PdfReader` directly wouldn't have worked — still
  unanswered, many sessions running now.
- Whether "anyone with access can share further" should be replaced
  with ownership tracking — an open, deliberately deferred design
  question, not a misunderstanding.

### What's next
- API gateway (build-order item 9) is next if the build order is
  followed strictly.
- No automated tests yet for anything built this session — the
  identity middleware, the permission repository, or the retrieval-time
  joins. Same standing gap as MCP and PII detection before it.
- The self-asserted `X-User-Id` (no real authentication behind it) and
  the unbounded re-sharing rule are both named, accepted limitations,
  not fixed — waiting on build-order item 14 for the former, an open
  design question for the latter.
- `CLAUDE.md` grew a new build-order item since last session — item 17,
  multi-agent federated retrieval, with its own Enterprise Requirement
  and a new "Multi-agent retrieval" section in the `ARCHITECTURE.md`
  template. Not started; now factored into the completion estimate
  below.

**Estimated completion: ~43% of the total project, by weighted effort**
— up from ~40% last session. 10 of 17 build-order items are done (the
denominator grew by one, since item 17 was added externally this
session). Rough remaining effort: ~77 hours across the test suite, real
auth/multi-tenancy (item 14), API Management, Azure deployment, the
frontend, guardrails (item 16), and multi-agent federated retrieval
(item 17) — the frontend and Azure deployment remain the two largest
untouched chunks, and item 17 is a genuinely large addition to the
remaining pool, not a small one. At 3–4 hours/day, that's roughly
20–26 working days left, assuming no scope changes.
