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

## Pending

- APIM request/response logging into Application Insights (unrelated to the Consumption-tier trade-offs, which are accepted permanently)
- Postgres cost fix — a start/stop script pair for the Azure Postgres server; saves nothing until the 12-month free-tier grant expires, so deliberately low priority
- Widen the remaining narrow-catch safe-wrappers in `retrieval_service.py` (query rewriting, graph-context lookup) to match the reranking fix — same shape of gap, not yet the demonstrated failure

## Time to finish

**~98% of the tracked build (weighted by real effort) is done.** What's
left is small, maintenance-shaped infrastructure and reliability work,
not a feature. Rough remaining effort: ~2 hours. At 3–4 hours/day,
well under 1 working day left — same standing caveat as always: a
genuinely new feature request would grow this number again.
