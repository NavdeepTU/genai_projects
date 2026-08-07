# ADR-017: MCP server, mounted over HTTP with a shared-secret gate

## Status
Accepted

## Context
With the query pipeline (hybrid search, reranking, LangGraph retry,
Neo4j graph context) and the evaluation harness both in place, the
core RAG pipeline was judged functionally complete — extraction,
chunking, embedding, retrieval, reranking, generation, with an
offline way to measure quality. The natural next step, build-order
item 10, is exposing that pipeline as a tool other AI clients (Claude
Desktop, other agents) can call directly through MCP (Model Context
Protocol) — a standard way for an AI client to discover and call
external tools without one-off integration code, instead of only
being reachable through this project's own chat-like query interface.

This reopened a question already discussed for items 7/8 (PII
detection, document-level access control): whether those needed to
come before MCP. The original reasoning for skipping ahead to MCP was
that a **local**, stdio-only MCP server adds no new network exposure —
nothing outside the machine can reach it, so the missing PII/ACL
layers aren't newly at risk. That reasoning was explicitly abandoned
once the decision was made to make the server **network-reachable
over HTTP** instead, in order to learn how this pattern actually works
in a real enterprise deployment. Going to HTTP meant a real gap opened
up: private documents and answers becoming reachable with nothing
checking who's asking. The resolution was to pull forward a minimal
slice of build-order item 14 (auth) — a single shared API key — ahead
of full PII/ACL, rather than fully building item 14 itself.

## Options considered
For where the MCP server runs:
1. **A standalone process**, its own transport, its own port.
2. **Mounted onto the existing FastAPI app**, under `/mcp`.

For the auth gate:
1. **Full item 14** (real user accounts, multi-tenancy, sessions) —
   the complete future feature, not a minimal slice.
2. **Per-caller API keys**, distinguishing which client made a call.
3. **One shared secret**, checked with a constant-time comparison.

For how the gate itself is implemented, once HTTP was the transport:
1. **Starlette's `BaseHTTPMiddleware`** with a `dispatch(request,
   call_next)` function — the more common, higher-level pattern.
2. **Raw ASGI middleware** — a class implementing
   `__call__(scope, receive, send)` directly.

## Decision
Mount the MCP server onto the existing FastAPI app rather than run it
standalone. Gate it with one shared secret (`MCP_API_KEY`, stored in
`.env` today, same as every other secret in this project, to move to
Key Vault at deployment). Implement that gate as raw ASGI middleware,
not `BaseHTTPMiddleware`. Expose two tools: `ask_knowledge_base` and
`upload_document`, both thin wrappers around the same
`RetrievalService` and `IngestionService` the REST routes already use.

## Reasoning
Standing up a separate process was rejected because every tool call
needs the same OpenAI/Voyage calls, the same circuit breakers, and the
same database and Neo4j access the REST routes already have — a
second process would mean either duplicating all of that wiring or
reaching across processes for it. Mounting onto the existing app gets
all of it for free, including inheriting `correlation_id_middleware`
automatically, since that middleware wraps the whole app regardless of
which mounted path a request eventually reaches.

Full item 14 was rejected as too large a scope change for this
feature — real multi-tenancy isn't needed yet because there's exactly
one caller type today. Per-caller keys were rejected for the same
reason: distinguishing callers only matters once there's more than one
kind of caller to distinguish. A single shared secret, compared with
`secrets.compare_digest` rather than `==` (to avoid leaking match
length through response timing), matches today's actual scale and
keeps the door shut to unauthenticated callers without over-building
for a multi-tenant future that doesn't exist yet.

`BaseHTTPMiddleware` was the first implementation, and it looked
correct by reading — but live testing (the same discipline this
project has relied on since the LangGraph retry-threshold and Voyage
rate-limit discoveries) showed the real key still failed with "SSE
stream ended without a response." `BaseHTTPMiddleware` runs whatever
it wraps in a separate task, piped through a queue — fine for an
ordinary request/response, but it breaks a response that's meant to
stay open and stream data over time, which is exactly what MCP's
protocol does. Raw ASGI middleware forwards `scope`, `receive`, and
`send` straight through with no intermediate task, and fixed it.

## Consequences
- New files: `app/mcp/auth.py` (`ApiKeyMiddleware`), `app/mcp/server.py`
  (`ask_knowledge_base`, `upload_document`), one new setting
  (`mcp_api_key`), and `main.py` wiring (a `lifespan` context manager
  plus the `/mcp` mount). New dependency: the official `mcp` Python SDK.
- **Found and fixed live, not caught by reading the code:** mounting a
  sub-app with `app.mount()` does not forward FastAPI's startup event
  into it — only the outer app's own lifespan runs automatically.
  Without explicitly entering `mcp.session_manager.run()` in a
  `lifespan` context manager, the MCP server's internal task group was
  never initialized, and every request failed with `RuntimeError: Task
  group is not initialized`, even past the auth check.
- **Found and fixed live:** `documents.py`'s pattern of writing the
  audit log entry *after* the best-effort graph-linking step was
  copied into `upload_document` at first, and carries a real gap — an
  unexpected (non-`CircuitOpenError`) failure during graph-linking
  would leave a document successfully ingested but with no audit trail
  at all. Fixed here by moving the audit log write to right after
  ingestion succeeds. The same gap still exists in `documents.py`
  itself; tracked for a later fix, not changed in this feature.
- Verified end-to-end through the real MCP protocol, not an in-process
  call: a throwaway client script confirmed a missing key and a wrong
  key both get rejected with 401, and a request with the correct key
  can list both tools, upload a test document, and get back a grounded
  answer citing content from that same upload.
- Known, accepted limitation: one shared secret means any holder of it
  is indistinguishable from any other in the audit log, and a leak
  grants full access with no per-caller revocation. Acceptable only
  because there's exactly one real caller type today — revisit once
  build-order item 14 exists.

## Scale, cost, and on-call reality
The shared secret is the sharpest edge here: it's a single point of
compromise with no way to revoke one caller without revoking everyone,
and no way to attribute a specific audit log entry to a specific
client beyond "held a valid key." That's a real production gap, not
just an interview talking point — acceptable today only because
there's one caller, unacceptable the moment a second real client shows
up without a follow-up fix.

Every MCP tool call opens its own database session and Neo4j session
by hand, since there's no FastAPI dependency injection outside of HTTP
routes to hand one to it. At meaningfully higher concurrency, MCP
traffic competes for the exact same connection pool `/query` and
`/documents/upload` already share — not a new ceiling MCP introduces,
but one more source of load against an existing, unchanged limit.

Mounting onto the existing app means MCP's fate is now tied to the
main app's: a redeploy or an outage of one takes down the other. That
trade-off was made deliberately, in exchange for real reuse of circuit
breakers, audit logging, and correlation IDs without duplicating any
of it — the alternative (a standalone process) would have traded that
shared-fate risk for a meaningfully bigger maintenance burden.

This is also the first time this project has exposed a write path
(document upload) through anything other than the FastAPI app's own
request cycle. That's exactly the kind of surface enterprise gateways
(rate limiting, request size limits, per-tenant quotas) exist to sit
in front of — none of which exists for MCP specifically yet, since
Azure API Management (build-order item 11) hasn't been built.
