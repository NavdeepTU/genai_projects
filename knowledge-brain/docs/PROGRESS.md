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
