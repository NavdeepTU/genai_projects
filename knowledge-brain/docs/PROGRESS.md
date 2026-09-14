# Knowledge Brain — Progress

A current-state snapshot, not a session history. Updated by `/end-session`:
a finished feature moves from Pending to Done, the estimate is re-stated,
and lines that are still correct are left untouched.

---

## Done

- Feature 1 — Document ingestion pipeline
- Feature 2 — Retrieval + answer generation
- Feature 3 — Hybrid search
- Cross-cutting — correlation IDs, audit log, circuit breakers
- Feature 4 — Reranking
- Feature 5 — LangGraph query pipeline
- Feature 6 — Neo4j document relationship graph
- Feature 7 — Evaluation harness
- Feature 8 — MCP server
- Feature 9 — PII detection
- Feature 10 — Tenant-level access control (originally document-level; retired to tenant-wide by ADR-047)
- Azure deployment — infrastructure, image, registry, going live
- Feature 11 — API Management gateway (Consumption tier trade-offs accepted permanently, see ADR-026)
- GitHub Actions CI/CD via OIDC
- Azure Postgres schema creation (now via Alembic, replacing the old hand-run script)
- Frontend foundation — shell, dark mode, document library
- Background upload processing with per-stage progress
- Query page — chat UI, sources, confidence
- Dashboard page
- Analytics page
- Admin page, gated by real authentication (session cookies + frontend)
- Scaling the deployed backend to zero
- LLM/RAG observability via LangSmith
- Real-time answer guardrails (input + output)
- Multi-agent federated retrieval
- Conversation history and the sidebar
- Context condensing and Redis
- Streamed answer generation
- Viewing a document, and Blob Storage
- Deleting a document, completely
- Multi-tenancy — tenant-wide sharing, per-user conversations
- PII human review workflow, including the admin reviewer UI
- Test-coverage hardening
- Alembic migrations
- Identity-lookup caching (Redis, 60s TTL, active invalidation on logout)
- Federated-retrieval failure-isolation fix (Voyage's own errors, not just an already-open circuit)
- Domain taxonomy — admin-managed domains replace free-text tags, fixing "HR" vs "Human Resources" vocabulary drift
- APIM request/response logging into Application Insights (metadata only, 100% sampling, verified live)
- Fixed a two-week silent deployment failure discovered while deploying the logging feature above: CI/CD had been failing at test collection since 2026-08-29 (missing settings, missing Redis service container), the real Container App was crash-looping on the same missing settings once CI was fixed, the API gateway's route catalog was a stale one-time import, the Docker image never included the migration tool, and the real Azure Postgres database still had a partial, pre-multi-tenancy schema. Every feature built in that two-week window — multi-tenancy, PII review, Alembic, this session's own domain taxonomy — had only ever been verified against local dev; a real end-to-end request now succeeds against the real deployment for the first time since 2026-08-29.
- Widened the remaining narrow-catch safe-wrappers in `retrieval_service.py` (query rewriting, graph-context lookup) to match the reranking fix — a fresh OpenAI or Neo4j failure now degrades gracefully instead of crashing the query, same as reranking already did
- Postgres cost fix — a manual `scripts/db.sh start|stop` script, reading the server name from Terraform's own outputs, so compute billing can be paused between work sessions (storage keeps billing regardless); Azure force-restarts a stopped server after 7 days regardless of this script — an accepted gap, not a bug in it
- Real Azure Cache for Redis — confirmed as a permanent, accepted cost trade-off (~$16/month, declined), same standing as APIM's Consumption tier. Production `REDIS_URL` stays a placeholder that always fails open; conversation-history and identity caching pay a database round trip in production, by design, not as an open gap. See CLAUDE.md's Enterprise Requirement 10.
- Deleting a conversation — hard delete (turns cascade, cache cleared, audit logged), mirroring how document deletion already works; user-requested, not on the original build order
- A read-only user profile page — email, role, organization, and join date, behind a new round icon in the header; served by a new `GET /users/me` endpoint kept deliberately separate from `/auth/me` so the extra tenant-name lookup doesn't tax every page load. Needs a Terraform re-apply after the next deploy before APIM forwards to it (not run yet — see the session's own reminder).

## Pending

Nothing. Every tracked feature and every named trade-off is either
built or permanently, deliberately accepted as-is.

## Time to finish

**100% of the tracked build (weighted by real effort) is done.** Zero
working days of build work remain — same standing caveat as always: a
genuinely new feature request would grow this number again.
