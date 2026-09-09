# Knowledge Brain

An enterprise-style RAG (Retrieval-Augmented Generation) platform: upload
internal documents, then ask questions about them in plain English and
get grounded answers — with the system openly admitting when it doesn't
know, instead of guessing.

Built as a hands-on learning project, one feature at a time, with a
written record of every significant decision (see [`docs/adr/`](docs/adr/))
and why it was made that way.

## Status

**Built and verified end-to-end:**
- **Document ingestion** — upload a PDF or `.txt` file → text is
  extracted → split into chunks → each chunk is embedded → everything is
  stored in Postgres. The REST upload endpoint returns immediately
  (extending [`ADR-001`](docs/adr/ADR-001-synchronous-ingestion.md)'s
  own stated next step); the pipeline runs afterward as a background
  task, with a `GET /documents/{id}/status` endpoint reporting which
  step it's currently on. MCP's `upload_document` tool stays fully
  synchronous, since a tool call only ever returns one final result.
  See [`ADR-030`](docs/adr/ADR-030-background-upload-processing.md).
- **Retrieval + hybrid search + answer generation** — ask a question →
  a vector search (meaning) and a keyword search (exact terms, via
  Postgres full-text search) run and get merged with Reciprocal Rank
  Fusion → an LLM answers using only that retrieved text.
- **Reranking** — hybrid search's top 20 candidates get re-scored by
  Voyage AI's reranker, which looks at the question and each chunk
  together instead of separately, before the best 5 reach the LLM. Falls
  back to hybrid search's own ranking if Voyage is unavailable.
- **LangGraph query pipeline** — the query flow is now a graph, not a
  fixed sequence: if the best reranked chunk scores below a relevance
  threshold, an LLM rewrites the question and the whole search runs
  again once before generating an answer, instead of quietly answering
  from weak results.
- **Neo4j document relationship graph** — after a document uploads, an
  LLM finds specific things it explicitly mentions (an error code, a
  ticket ID) and links it in Neo4j to any other document that actually
  defines that thing. A query then pulls in one hop of that context
  alongside its retrieved chunks — real connections, not just similar
  wording. Best-effort, same as reranking: falls back to answering from
  retrieved chunks alone if Neo4j is unavailable.
- **Correlation IDs, an append-only audit log, and circuit breakers**
  around every external AI call (OpenAI, Voyage, and Neo4j) — see [`docs/adr/ADR-007`](docs/adr/ADR-007-enterprise-requirements-retrofit-scope.md)
  for why the first three were prioritized over other pending requirements.
- **Evaluation harness** — a fixed set of known-answer test questions,
  run through the real pipeline against a small dedicated set of
  fixture documents, scored on retrieval correctness, faithfulness, and
  answer correctness (the last two via a separate LLM-as-judge call
  each). An offline, on-demand tool, not part of the running app — see
  [`ADR-016`](docs/adr/ADR-016-llm-judge-evaluation-harness.md).
- **MCP server** — the same pipeline, exposed as two tools
  (`ask_knowledge_base`, `upload_document`) other AI clients can call
  directly over HTTP, mounted on this same app at `/mcp` and gated by a
  shared API key. Reuses every service, circuit breaker, and the audit
  log the REST routes already use — see
  [`ADR-017`](docs/adr/ADR-017-mcp-server.md).
- **PII detection** — before any document is chunked or embedded, its
  text is checked by Azure AI Language against an explicit 14-category
  allowlist (names, contact info, financial data, US and India
  government IDs). Any match holds the document for human review
  instead of embedding it automatically — `pending_review`, not
  searchable unless and until an admin approves it (see the review
  workflow below). Runs inside the shared ingestion service, so it
  protects the REST upload endpoint and the MCP tool automatically.
  Fails closed, not open, if Azure itself is unavailable — see
  [`ADR-018`](docs/adr/ADR-018-pii-detection.md).
- **PII review workflow** — a flagged document isn't a dead end. Its
  uploader submits it into an admin review queue, scoped to that
  document's own tenant (an admin never reviews another tenant's
  flagged content); an admin approves it (re-running the full ingestion
  pipeline on the original text, PII included — a deliberate, audited
  human override of "never embed raw PII," not a redaction step) or
  rejects it (terminal, no resubmission). A held document is visible
  only to its own uploader and to admins of its tenant, the one
  exception to tenant-wide sharing below. See
  [`ADR-048`](docs/adr/ADR-048-pii-review-workflow.md).
- **Multi-tenancy** — every user and document belongs to one tenant (a
  company/workspace); documents are shared with everyone in the tenant
  that uploaded them, no per-document grant needed, while conversations
  stay private to the individual user. A user picks their tenant at
  signup from an already-registered list (`GET /tenants`, public);
  only an admin can register a new one (`POST /admin/tenants`).
  Retrieval — vector search, keyword search, and graph-context
  snippets alike — is filtered by a SQL join against `documents.tenant_id`
  before results are ever ranked, not after, replacing the earlier
  per-user grant table this project used until this feature. See
  [`ADR-046`](docs/adr/ADR-046-multi-tenancy.md); the per-document
  restriction Enterprise Requirement 5 originally called for on top of
  tenant sharing was retired once tenant-wide sharing was confirmed as
  the actual intended design, not a step toward something finer — see
  [`ADR-047`](docs/adr/ADR-047-retire-per-document-acl-requirement.md).
- **Real authentication** — email/password login with the project's
  own server-side session cookies, not JWT and not an external
  identity provider, chosen specifically to build the real mechanics
  hands-on. `POST /auth/signup` hashes a password with Argon2id
  (`argon2-cffi`, not the unmaintained `passlib`) before it's ever
  stored; `POST /auth/login` verifies it and hands back a random,
  unguessable session token as an `httponly` cookie — never the
  session row's own database id, so a value that routinely appears in
  this project's logs is never the same value that would let someone
  log in. Every REST endpoint requires that cookie to resolve to a
  real, unexpired session; MCP is deliberately unchanged, since a
  non-browser client can't hold a session cookie the same way — it
  keeps its existing shared-API-key-plus-`X-User-Id` model. The
  frontend has real `/login` and `/signup` pages now too: a route
  handler calls the backend server-to-server and re-issues the
  resulting session token as this app's own cookie, and a cheap
  edge-level check (`proxy.ts`) redirects an unauthenticated visitor
  to `/login` before a protected page ever renders. See
  [`ADR-036`](docs/adr/ADR-036-real-authentication-session-cookies.md)
  (backend) and
  [`ADR-037`](docs/adr/ADR-037-real-authentication-frontend.md)
  (frontend).
- **LLM/RAG observability** — every OpenAI and Voyage call (embedding,
  generation, query rewriting, reference extraction, reranking) now
  reports its exact prompt, exact response, tokens, cost, and latency
  to [LangSmith](https://www.langchain.com/langsmith), a dedicated
  external tool — not built into this app's own UI, a deliberate
  choice. Since the query pipeline is already a LangGraph graph,
  turning tracing on captures its whole execution automatically, node
  by node; the OpenAI calls get this by wrapping each service file's
  client once with `wrap_openai()`, Voyage's reranking call via an
  explicit `@traceable` decorator (no automatic dollar cost there,
  since LangSmith's pricing table doesn't know Voyage's rates). Every
  query's trace is tagged with who asked. See
  [`ADR-038`](docs/adr/ADR-038-llm-rag-observability.md).
- **Real-time guardrails, input and output** — every question and every
  generated answer each pass through their own pair of independent
  checks. On the way in: a moderation check plus an LLM jailbreak
  judge, run before retrieval — a flagged or doubly-unreachable
  question never triggers an embedding call, a search, or a generation
  call at all. On the way out: a moderation check plus an LLM injection
  judge, shown the actual retrieved context alongside the generated
  answer, asked whether the answer looks like it followed instructions
  smuggled into a document rather than genuinely answering the question
  — the RAG-specific risk a moderation classifier alone can't catch.
  Either side's flag replaces the real content with the same fixed,
  friendly message, sources and confidence both suppressed too, never
  revealing which check tripped. The fail policy is availability-aware
  on both sides: a single check being down contributes no signal of its
  own, but the combined decision still fails closed if neither check
  could run at all. Verified live: a real injection payload uploaded as
  a document was correctly blocked on the way out; a real jailbreak
  attempt was blocked on the way in roughly 3x faster than a full
  pipeline run, since nothing downstream ever executes. Both run as
  real steps in the query pipeline's LangGraph graph — the input check
  is now the graph's actual entry point — so MCP inherits both
  automatically. See
  [`ADR-039`](docs/adr/ADR-039-real-time-answer-guardrails.md).
- **Multi-agent federated retrieval** — documents can now be tagged
  with one or more free-text domains at upload (manual, for now); a
  supervisor LLM call decides which of a user's own domains a question
  actually needs. Zero or one domain — every question today, since
  domains are opt-in — costs exactly what it always did. Two or more
  domains runs one full retrieval-and-generation pass per domain,
  concurrently, each producing its own independent draft answer, then a
  synthesis call merges them into one response with reconciled
  citations, which gets one more guardrails pass before it returns. A
  failing domain is excluded via task-level isolation rather than a
  literal per-domain circuit breaker — this project's breakers are
  already one shared instance per external service, not per domain — a
  deliberate deviation from the build spec's literal wording, flagged
  and approved before building. Verified live: a genuinely cross-domain
  question correctly merged findings from two real domain-tagged
  documents, at roughly double a single-domain question's latency. A
  real gap found the same session — a raw provider rate-limit error
  wasn't caught by this feature's failure isolation the way a
  circuit-breaker error was, so one domain hitting it could fail the
  whole question — was fixed in a later session: both this feature's
  own safety net and reranking's underlying one now catch Voyage's own
  error class directly, confirmed with a test reproducing the exact
  scenario. See
  [`ADR-040`](docs/adr/ADR-040-multi-agent-federated-retrieval.md).
- **Conversation history, a real sidebar, and context condensing** —
  every question now belongs to a persisted conversation, not just
  whatever the browser's memory still holds. A sidebar lists a user's
  conversations, most recently active first; resuming one is a real
  route (`/query/[conversationId]`), not client-side state, so a reload
  actually brings back the same thread. A new conversation is only
  created once its first answer comes back successfully, and a named
  conversation's ownership is checked *before* the safety/retrieval
  pipeline runs, so a bad or someone else's id fails with a 404 rather
  than after paying for a full pipeline run. A follow-up like "what
  about the other one" is now rewritten into a standalone question —
  always, on every follow-up — using the conversation's last 3 turns as
  context, before it ever touches retrieval; the input guardrail then
  checks that rewritten text, not the raw one. Those recent turns come
  from Redis (this project's first use of it, introduced only once
  condensing gave it a real job) when cached, falling back to the
  conversation's own already-loaded turns — never a crash — when the
  cache is cold, holds something unexpected, or Redis itself is
  unreachable. See
  [`ADR-041`](docs/adr/ADR-041-conversation-history-and-sidebar.md) and
  [`ADR-042`](docs/adr/ADR-042-context-condensing-and-redis.md).
- **Azure deployment** — the real backend (not a placeholder) is live
  in Azure: a Terraform module (`infra/`) provisions a resource group,
  Postgres Flexible Server, Key Vault, a container registry, and a
  Container App, wired together with a Managed Identity instead of any
  raw secret; Key Vault holds all 7 real secrets the app needs. Its
  public URL returns a real HTTP 200 with a genuine Swagger UI and a
  correlation ID header. The Container App scales to zero after 5
  minutes of no traffic (Azure Cost Management surfaced it running,
  and billing, continuously since first deploy) — the first request
  after any idle period pays a real several-second cold start, both
  through the REST API and MCP, which share the same container. See
  [`ADR-020`](docs/adr/ADR-020-azure-deployment-infrastructure.md),
  [`ADR-021`](docs/adr/ADR-021-containerizing-the-backend.md),
  [`ADR-022`](docs/adr/ADR-022-deploying-the-real-backend-image.md)
  (which also covers a real deploy failure — an image built for the
  wrong CPU architecture — diagnosed and fixed live), and
  [`ADR-035`](docs/adr/ADR-035-container-app-scale-to-zero.md).
- **GitHub Actions CI/CD** — an OIDC-authenticated workflow (no stored
  Azure secret) that tests, builds for `amd64` explicitly, pushes, and
  deploys on every push to `main`. Verified live with a real,
  unassisted, successful end-to-end run. See
  [`ADR-023`](docs/adr/ADR-023-ci-owns-the-deployed-image.md),
  [`ADR-024`](docs/adr/ADR-024-github-actions-oidc.md), and
  [`ADR-025`](docs/adr/ADR-025-ci-cd-first-real-run.md) (three more
  real bugs — a missing CI test database, a GitHub OIDC subject claim
  mismatch, and an Azure revision-naming limit — found only once the
  pipeline actually ran).
- **API Management gateway** — Azure API
  Management sits in front of the backend, importing its API definition
  straight from FastAPI's own OpenAPI spec and stamping a Key
  Vault-held secret onto every request it forwards; the backend rejects
  anything missing it. Verified live end-to-end: a real request through
  the gateway returns the correct `401`. Network-level restriction and
  real per-caller rate limiting both require a paid APIM tier
  (Developer/Premium, for VNet integration and `rate-limit-by-key`);
  this project stays on the Consumption tier deliberately, so both stay
  out of scope by choice, not by gap — see
  [`ADR-026`](docs/adr/ADR-026-api-management-gateway.md). Structured
  request/response logging into Application Insights is unrelated to
  tier and remains genuinely unbuilt.
- **Frontend** *(all five planned pages built — see below)* — a
  separate Next.js project (`frontend/`, Tailwind, Shadcn/UI on Base
  UI) with a shared shell (navigation, dark mode, a responsive mobile
  menu). The Dashboard, at the app's root, is a real digest — total
  documents and recent queries are pulled from data that already
  exists, with two data-less widgets (retrieval accuracy, cost per
  query) showing an honest "not tracked yet" state instead of a
  fabricated number. The Document Library — backed by a
  tenant-filtered `GET /documents` endpoint — fetches server-side
  from a Next.js Server Component rather than the browser, avoiding the
  backend needing any CORS configuration. Drag-and-drop upload is built
  too, with a live per-stage progress bar. A document uploaded today can
  be opened directly in the browser (its original file, saved to Azure
  Blob Storage at upload time — see `ADR-044`) and deleted completely —
  its row, chunks, file, and graph node all removed,
  behind a real confirmation dialog (see `ADR-045`). The Query page is a real
  chat interface: `/query`'s response carries `sources` (the
  chunks that actually informed the answer, with filenames) and
  `confidence` alongside the answer text, not just the answer alone. A
  single-domain question now streams for real, sentence by sentence
  over Server-Sent Events (`POST /query/stream`), with a resumable
  sidebar of past conversations and context-condensed follow-ups — see
  `ADR-041`, `ADR-042`, and `ADR-043`. The Analytics page
  adds a real, genuinely new metric — average response time, timed
  once inside `RetrievalService.run_query` so both REST and MCP queries
  count toward it — plus a hand-rolled (no new dependency) 30-day query
  volume chart and top questions, alongside one more honest "not
  tracked yet" placeholder for retrieval accuracy. The Admin page is
  the first page in this project gated by an access check —
  `require_admin`, checking a real `User.is_admin` column (originally
  a small `ADMIN_USER_IDS` allowlist, upgraded once real accounts
  existed — see `ADR-036`) rather than full RBAC, since it's the first
  page that reads across every user instead of just the caller's own —
  showing a real audit log viewer and, since `ADR-046`, a real
  tenant-management panel (list every registered tenant, register a
  new one). Every client-triggered action
  talks only to same-origin Next.js Route Handlers, which proxy the
  real, secret-bearing calls to the backend server-to-server, so
  `BACKEND_GATEWAY_SECRET` never reaches client-side JavaScript. See
  [`ADR-028`](docs/adr/ADR-028-frontend-stack-and-base-ui.md),
  [`ADR-029`](docs/adr/ADR-029-document-library-page.md),
  [`ADR-030`](docs/adr/ADR-030-background-upload-processing.md),
  [`ADR-031`](docs/adr/ADR-031-query-page.md),
  [`ADR-032`](docs/adr/ADR-032-dashboard-page.md),
  [`ADR-033`](docs/adr/ADR-033-analytics-page.md),
  [`ADR-034`](docs/adr/ADR-034-admin-page.md),
  [`ADR-037`](docs/adr/ADR-037-real-authentication-frontend.md),
  [`ADR-044`](docs/adr/ADR-044-document-viewing-and-blob-storage.md),
  [`ADR-045`](docs/adr/ADR-045-document-deletion.md), and
  [`ADR-046`](docs/adr/ADR-046-multi-tenancy.md).

**Known gaps, tracked on purpose, not forgotten:**
- The automated test suite (`tests/`, 216 tests) covers ingestion
  end-to-end, chunking, extraction, PII detection's "flag and stop"
  branch, the dashboard's and analytics page's repository/service
  methods, the query pipeline's source/confidence-building logic,
  `require_admin`, real authentication (signup, login, logout, session
  expiry), both guardrail nodes' full decision tables (input and
  output, each: both checks clean, either flagging alone, one down with
  the other clean, one down with the other flagging, both down),
  federated retrieval's own routing logic (single/multi-domain,
  classification-unavailable fallback, a failing domain marked partial,
  every domain failing, every domain's own guardrail blocking, the
  synthesized answer itself getting blocked, `prepare_for_generation`'s
  single/multi-domain split), conversation storage (creation, turn
  storage, the sidebar-ordering timestamp bump, user-scoped listing,
  the stranger-gets-`None` permission check), context condensing (the
  full decision table for whether/how to condense, the seed/append/trim
  behavior of the recent-turns cache, and — a deliberate exception to
  this project's usual rule against unit-testing thin external-service
  wrappers — the Redis cache's fail-open behavior tested directly,
  since that behavior *is* the point of the module), and streamed
  answer generation (`stream_answer`'s empty-choices guard,
  `stream_checked_answer`'s full event matrix: success, an
  immediately-retracting flagged sentence, moderation unavailable,
  generation failing mid-stream, injection flagging after the answer
  was shown, injection unavailable, a trailing sentence with no closing
  punctuation), document viewing (`blob_storage.py`'s dual local/production
  auth-path selection and its upload/download/delete functions,
  `create_document`'s blob save and its graceful-degradation path when
  storage is unreachable, `Document.has_file`), and document deletion
  (`DocumentRepository.delete_document`'s cascade — checked against a
  real database, not assumed — `DocumentDeletionService`'s full
  failure-isolation matrix, `GraphRepository.delete_document_node`), and
  multi-tenancy (`TenantRepository` CRUD, tenant-scoped and
  cross-tenant-exclusion cases in `DocumentRepository`, tenant-aware
  auth/ingestion/federated-retrieval tests, and two dedicated
  cross-tenant graph-leak regression tests), the PII review workflow
  (visibility and state-transition tests, `approve_and_process`'s
  reprocessing and failure paths, the cross-tenant admin-scoping check),
  and — closed in one pass, no application code changed — every
  previously-named standing gap: hybrid search's RRF math, the
  hand-built circuit breaker's own state machine, the audit log's write
  path, the Neo4j repository's `create_reference`/`get_referenced_documents`,
  the actual compiled LangGraph retry loop (not just the routing
  function in isolation), PII detection's paragraph-splitting and
  Azure-batching logic, and MCP's two tools (previously zero coverage,
  driven directly as plain functions). No
  dedicated route-level tests exist for `/query/stream` or `/query` —
  consistent with this project's convention of testing the service
  layer directly and verifying route wiring live instead, though every
  document and admin route (including the PII review routes) is tested
  this same way, by calling the route function directly. The frontend has its own test
  suite too (`frontend/`, 43 tests, Vitest + React Testing Library) —
  covering the domain-tagging upload field and its document-card
  badges, the conversation sidebar, the chat component's resume
  behavior, live streamed-chunk rendering and retract handling, a
  dedicated `streamQuery` SSE-parsing test (a frame split across reads,
  multiple frames in one read, a multi-byte character split
  mid-character), the document card's "View" link, "Not viewable",
  "Send for review", "in review", and "rejected" states, the delete
  confirmation dialog's full behavior (opening, cancelling, a
  successful delete, an inline error, a 401 redirect), and the Admin
  page's review-queue section (rendering a flagged document with its
  uploader's email, the empty state, and a document leaving the queue
  once approved); run with `npm test` inside `frontend/`.
- Outside the PII review workflow specifically, there's still no
  ownership or per-document restriction concept within a tenant more
  generally — every user in a tenant can view, share, and permanently
  delete every *normal* document that tenant owns, with no
  finer-grained restriction available. This was originally recorded as
  a gap against this project's own written Enterprise Requirement 5;
  that requirement was itself retired (`ADR-047`) once tenant-wide
  sharing was confirmed as the intended design, not an incomplete step
  toward something finer — so this is now a settled design choice, not
  an open gap. See `ADR-045`, `ADR-046`, and `ADR-047`.
- Deleting a document's file from Blob Storage and its node from Neo4j
  are both best-effort — an outage in either is logged and skipped,
  never blocks the deletion itself. This means a rare Blob Storage or
  Neo4j hiccup during a delete can leave an orphaned file or graph node
  behind with nothing pointing at it any more. There's also no
  soft-delete or undo of any kind — the confirmation dialog is the only
  safety net. See `ADR-045`.
- The answer guardrails add two real LLM calls to every query, safe
  ones included, and the input guardrail adds two more on top before
  retrieval even starts — a genuine, felt cost, not a false-positive
  concern. The injection judge reuses `generation_model` rather than a
  cheaper/faster model, and runs even when nothing was actually
  retrieved. Neither is wrong, both are real, un-taken levers if the
  added cost ever needs trimming. See `ADR-039` and `ADR-040`.
- Domain tags are free-text with no vocabulary control and no dedup
  across documents — "HR" and "Human Resources" are two unrelated
  domains to this system, and nothing today detects or merges
  near-duplicate names. See `ADR-040`.
- Context condensing adds one more LLM call to every follow-up
  question, unconditionally — no cheaper "does this actually need
  rewriting" check first, a deliberate choice over a smarter but
  occasionally-wrong detection step. It also has the same structural
  limit as the injection judge and the domain classifier: it's an LLM,
  with no formal guarantee it produces a faithful rewrite rather than a
  subtly wrong one, and nothing today would notice if it did. See
  `ADR-042`.
- Streaming's injection check can only retract an already-streamed
  answer, not prevent it from being shown at all — it needs the
  *complete* answer to judge whether retrieved content hijacked it,
  which by definition doesn't exist until every sentence has already
  been sent. This is the one place in the system where unchecked model
  output can be visible to a user, even briefly. A cross-domain question
  gets no real token streaming either — each domain still generates a
  full draft answer first, and the synthesized result arrives as one
  piece. See `ADR-043`.
- There's no rate limiting on `/auth/login` — nothing beyond Argon2id's
  own deliberately-slow hashing cost stands between a script and a
  password-guessing attempt. Sessions also have a fixed 7-day lifetime
  with no sliding renewal or a "log out everywhere" control. See
  `ADR-036`.
- The audit log's "nobody can edit or delete an entry" guarantee is
  enforced at the code level only — the local database connection is a
  superuser and could bypass a real database-level restriction. See
  [`ADR-009`](docs/adr/ADR-009-audit-logging-approach.md).
- The circuit breaker's state lives in a single process's memory, so it
  doesn't share failure counts across multiple server instances yet.
- Schema changes now go through Alembic (a single baseline migration
  capturing the schema as of this project's Azure Postgres setup — see
  [`ADR-027`](docs/adr/ADR-027-azure-postgres-schema-creation.md) for
  how that original schema was created by hand, before Alembic
  existed), but running `alembic upgrade head` is still a manual step
  you run yourself, locally and against Azure; it isn't wired into
  CI/CD the way deploying a new image already is.

## How it works

```mermaid
flowchart LR
    U[User uploads a file] --> UP[POST /documents/upload]
    UP --> PIPE["extract → chunk → embed → store<br/>(Postgres + pgvector)"]

    Q[User asks a question] --> QR[POST /query]
    QR --> RAG["embed → find nearest chunks<br/>→ LLM answers from retrieved text"]

    PIPE -. shares .-> DB[(Postgres)]
    RAG -. reads .-> DB
```

Every REST request must also carry a real, logged-in session cookie
(MCP keeps its own separate shared-key model) — every document is only
visible to users explicitly granted access to it, and a request
without a valid session is rejected outright, before it reaches any
route. Every request also gets a
correlation ID (for tracing), an audit log entry (for accountability),
and OpenAI calls are protected by a circuit breaker (so one bad outage
doesn't cascade). Full diagrams and the reasoning behind every choice
live in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Tech stack (what's actually running today)

- **FastAPI** — the web server
- **PostgreSQL + pgvector** — one database for both normal data and
  vector similarity search (see [`ADR-002`](docs/adr/ADR-002-pgvector-before-qdrant.md)
  for why not a dedicated vector DB, yet)
- **OpenAI** — `text-embedding-3-small` for embeddings,
  `gpt-4o-mini` for answer generation
- **Voyage AI** — `rerank-2.5-lite` for reranking hybrid search's results
  before generation (see [`ADR-013`](docs/adr/ADR-013-reranking-with-voyage-ai.md))
- **LangGraph** — the query pipeline itself: a graph with one conditional
  loop back to a rewritten search when retrieval comes back weak (see
  [`ADR-014`](docs/adr/ADR-014-langgraph-query-pipeline.md))
- **Neo4j** — the document relationship graph: explicit `REFERENCES`
  links between documents, extracted from content, not similarity (see
  [`ADR-015`](docs/adr/ADR-015-neo4j-document-relationship-graph.md))
- **MCP (Model Context Protocol)** — the official Python SDK, mounted
  onto this same app so other AI clients can call the pipeline directly
  (see [`ADR-017`](docs/adr/ADR-017-mcp-server.md))
- **Azure AI Language** — PII detection at ingestion time, scoped to an
  explicit category allowlist rather than its full default set (see
  [`ADR-018`](docs/adr/ADR-018-pii-detection.md)) — this project's
  first real Azure dependency
- **SQLAlchemy (async) + `uv`** — ORM and dependency management
- **Docker** — runs Postgres and Neo4j locally, isolated from anything
  else on the machine (see [`ADR-003`](docs/adr/ADR-003-postgres-in-docker.md))
- **Next.js + Tailwind + Shadcn/UI (on Base UI)** — the frontend
  (`frontend/`), complete: a shared shell and all five planned
  pages (see [`ADR-028`](docs/adr/ADR-028-frontend-stack-and-base-ui.md))
- **LangSmith** — traces every OpenAI/Voyage call: prompt, response,
  tokens, cost, latency, tied naturally into LangGraph since the query
  pipeline is already one (see
  [`ADR-038`](docs/adr/ADR-038-llm-rag-observability.md))

The full planned stack (Kafka, Qdrant, Azure) is documented in
`CLAUDE.md` — most of it isn't built yet, and is being added
deliberately, one justified decision at a time, not upfront. Redis
joined the built list this session (see conversation history, above) —
introduced only once a real feature (context condensing) actually
needed it, not ahead of time.

## Run it locally

1. **Start Docker Desktop**, then start Postgres, Neo4j, and Redis:
   ```
   docker compose up -d
   ```
2. **Enable the pgvector extension** (one-time, per fresh database volume):
   ```
   docker exec knowledge-brain-postgres psql -U knowledge_brain -d knowledge_brain -c "CREATE EXTENSION IF NOT EXISTS vector;"
   ```
3. **Copy the environment file** and add your own OpenAI and Voyage AI
   API keys:
   ```
   cp .env.example .env
   ```
   The `NEO4J_*` and `REDIS_URL` values already match
   `docker-compose.yml`'s defaults, so they work as-is for local
   development. Set `MCP_API_KEY` to any
   value of your choice — it's the shared secret MCP clients must send
   back to use the `/mcp` endpoint. Set `APIM_GATEWAY_SECRET` to any
   value too — in Azure this is generated and stamped on automatically
   by API Management (see [`ADR-026`](docs/adr/ADR-026-api-management-gateway.md)),
   but locally there's no gateway in front of the app, so every request
   needs to send this same value back manually as an `X-Gateway-Secret`
   header, or the backend rejects it with a 401. `AZURE_LANGUAGE_ENDPOINT` and
   `AZURE_LANGUAGE_KEY` need a real Azure AI Language resource (the
   free `F0` tier is enough) — create one in the
   [Azure Portal](https://portal.azure.com), search "Language service,"
   and copy its endpoint and key from the resource's "Keys and
   Endpoint" page. `ENVIRONMENT` defaults to `dev`, which keeps the
   session cookie (see "Trying it manually" below) usable over plain
   `http` locally — leave it as `dev` unless you're running this
   somewhere with real TLS in front of it. To use the Admin page
   locally, sign up a user (see below) and then flip that row's
   `is_admin` to `true` directly in Postgres — there's no allowlist
   setting anymore, since `require_admin` checks a real column now
   (see `ADR-036`). `LANGSMITH_API_KEY` needs a real key from a free
   [LangSmith](https://smith.langchain.com) account — without one,
   every OpenAI/Voyage call still works exactly the same, it just won't
   show up anywhere to look at afterward (see `ADR-038`).
4. **Install dependencies:**
   ```
   uv sync
   ```
5. **Create the database tables** (one-time, per fresh database volume):
   ```
   uv run alembic upgrade head
   ```
6. **Run the server:**
   ```
   uv run uvicorn app.main:app --reload --port 8000
   ```

Once it's running, interactive API docs (Swagger UI) are available at
`http://localhost:8000/docs` — the fastest way to try both endpoints
without writing any `curl` commands by hand.

### Trying it manually

Every REST request needs a real, logged-in session now (see
[`ADR-036`](docs/adr/ADR-036-real-authentication-session-cookies.md)),
plus an `X-Gateway-Secret` header matching whatever value you set for
`APIM_GATEWAY_SECRET` in `.env` (see step 3 above; in Azure, API
Management adds this header automatically, but locally you have to
send it yourself). Signing up also needs a real `tenant_id` (see
[`ADR-046`](docs/adr/ADR-046-multi-tenancy.md)) — on a fresh database
there's no tenant yet and no admin to register one through the API
either, so bootstrap the first one directly:

```
docker exec knowledge-brain-postgres psql -U knowledge_brain -d knowledge_brain \
  -c "INSERT INTO tenants (id, name) VALUES (gen_random_uuid(), 'Acme') RETURNING id;"
```

Copy the `id` it prints, then sign up and log in — `curl -c cookies.txt`
saves the session cookie login sets, `-b cookies.txt` sends it back on
every call after:

```
curl -X POST http://localhost:8000/auth/signup \
  -H "X-Gateway-Secret: your-apim-gateway-secret-here" \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "a-real-password", "tenant_id": "<the tenant id from above>"}'

curl -X POST http://localhost:8000/auth/login -c cookies.txt \
  -H "X-Gateway-Secret: your-apim-gateway-secret-here" \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "a-real-password"}'
```

Once at least one tenant exists, `GET /tenants` (no auth needed — it's
the same list a real signup form's picker uses) is the normal way to
find its id instead of reading it back from Postgres:

```
curl http://localhost:8000/tenants -H "X-Gateway-Secret: your-apim-gateway-secret-here"
```

From here, every call just needs `-b cookies.txt` instead of an
`X-User-Id` header:

```
curl -X POST http://localhost:8000/documents/upload -b cookies.txt \
  -H "X-Gateway-Secret: your-apim-gateway-secret-here" \
  -F "file=@/path/to/a/file.txt"

curl -X POST http://localhost:8000/query -b cookies.txt \
  -H "X-Gateway-Secret: your-apim-gateway-secret-here" \
  -H "Content-Type: application/json" \
  -d '{"question": "What does this document say?"}'
```

The upload call returns immediately with `status: "pending"` — the file
hasn't actually been processed yet. Take the `id` it returns and poll
the status endpoint (the frontend does this automatically, every 2
seconds) to watch it move through `processing`/`processing_stage` and
on to `ready`:

```
curl http://localhost:8000/documents/<document-id>/status -b cookies.txt \
  -H "X-Gateway-Secret: your-apim-gateway-secret-here"
```

The `/query` response above carries more than just `answer`: a
`sources` array (the chunks actually used, each with its source
document's filename) and a `confidence` number — the reranker's own
relevance score on the best chunk, or `null` if reranking itself was
unavailable for that request.

A document uploaded today is automatically visible to every user in
the uploader's own tenant — no separate share step exists anymore (see
[`ADR-046`](docs/adr/ADR-046-multi-tenancy.md)). To see this directly,
sign up a second user with the *same* `tenant_id` and list documents
from their own session — the first user's upload shows up immediately,
with no grant of any kind:

```
curl -X POST http://localhost:8000/auth/signup \
  -H "X-Gateway-Secret: your-apim-gateway-secret-here" \
  -H "Content-Type: application/json" \
  -d '{"email": "someone-else@example.com", "password": "a-real-password", "tenant_id": "<the same tenant id>"}'

curl -X POST http://localhost:8000/auth/login -c cookies2.txt \
  -H "X-Gateway-Secret: your-apim-gateway-secret-here" \
  -H "Content-Type: application/json" \
  -d '{"email": "someone-else@example.com", "password": "a-real-password"}'

curl http://localhost:8000/documents -b cookies2.txt \
  -H "X-Gateway-Secret: your-apim-gateway-secret-here"
```

To see isolation the other way — a user in a *different* tenant seeing
none of this — bootstrap a second tenant the same way as the first,
and sign a third user up into it instead: `GET /documents` for that
account comes back empty.

MCP tools (`ask_knowledge_base`, `upload_document`) are also reachable
at `http://localhost:8000/mcp`, over the Streamable HTTP transport, for
any MCP-compatible client (e.g. Claude Desktop) — MCP was deliberately
**not** migrated to session cookies (it can't hold one the way a
browser does), so it still authenticates with the shared secret you set
as `MCP_API_KEY` in an `X-API-Key` header, plus an `X-User-Id` header —
no longer purely self-asserted, though: since `ADR-046`, that header
must be a real, registered user's id, checked against the database, or
the request is rejected.

### Running the frontend

The backend needs to already be running (see above). From a separate
terminal:

```
cd frontend
npm install
```

Create `frontend/.env.local` with one line, matching whatever
`APIM_GATEWAY_SECRET` is set to in the backend's own `.env`:

```
BACKEND_GATEWAY_SECRET=your-apim-gateway-secret-here
```

Then start it:

```
npm run dev
```

Visit `http://localhost:3000`. All five planned pages exist (Dashboard,
Document Library, Query, Analytics, Admin) — you'll land on `/login`
first if you don't have a session yet. Sign up (or log in, if you
already have an account) and you're in; see real authentication, above,
and [`ADR-037`](docs/adr/ADR-037-real-authentication-frontend.md) for
how the frontend and backend sessions connect.

Run the frontend's own test suite with:

```
npm test
```

One real gotcha worth knowing about: documents uploaded through the
browser *before* real auth existed were granted to a placeholder
identity (`"dev-user"`) that no real login can ever produce again — if
you're picking this project back up after that change, those old
documents will look like they've vanished (they're still in Postgres,
just permanently unreachable through the app now). Re-upload them under
your real account.

### Running the evaluation harness

```
PYTHONPATH=. uv run python eval/run_eval.py
```

Ingests its own small set of fixture documents the first time it runs
(skipped on later runs), then reports retrieval, faithfulness, and
correctness scores for a fixed set of known-answer test questions.
Paced to stay under Voyage's free-tier rate limit, so a full run takes
a couple of minutes, not seconds.

## Project documentation

This project keeps a written record of *why*, not just *what* — useful
for picking the project back up after time away, and for interview prep.

| File | What it's for |
|---|---|
| `CLAUDE.md` | The operating rules for how this project gets built, including the full build order and enterprise requirements |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How the system actually works right now, with diagrams — always current, never aspirational |
| [`docs/PROGRESS.md`](docs/PROGRESS.md) | A dated history log of every session: what was built, what was hard, what's next |
| [`docs/INTERVIEW_PREP.md`](docs/INTERVIEW_PREP.md) | A plain-language study sheet — the Q&A behind every major decision, meant to be reviewed before an actual interview |
| [`docs/adr/`](docs/adr/) | One Architecture Decision Record per significant choice: what was considered, what was picked, and why |
| [`docs/pipeline-status.html`](docs/pipeline-status.html) | A visual, at-a-glance dashboard of what's built vs. pending |
