# ADR-019: Document-level access control

## Status
Accepted

## Context
Build-order item 8. Chosen directly after PII detection, with the same
kind of concrete motivation that drove that feature rather than "it's
next on the list": with MCP's `upload_document` and `/documents/upload`
both live, uploaded documents are now genuinely confidential material
entering the system through two network-reachable doors, with nothing
yet restricting who can retrieve their contents once they're in.
Enterprise Requirement 5 calls for a permission filter checked "at
retrieval time — not after," intersecting retrieved chunks with a
per-user, per-document ACL stored in Postgres.

This immediately ran into a real prerequisite gap, flagged as far back
as `ADR-007`: document-level access control needs something to check
access *for*, and this project has no user model — real auth
(login, sessions) is deferred to build-order item 14, much later.

## Options considered
For identity, before any of the ACL logic itself:
1. **Defer this whole feature until item 14 (real auth) exists.**
2. **A lightweight stand-in** — a plain `user_id` string the caller
   sends per request, no password, no session — just enough to make
   "does this user have access" a real question, the same way MCP
   pulled forward a minimal API key ahead of full auth last session.

For how identity gets delivered to a request:
1. **A FastAPI `Depends()`**, checked per-route.
2. **Middleware + `ContextVar`**, mirroring `correlation_id_middleware`
   exactly — wraps the whole app, REST and `/mcp` both, automatically.

For who can share a document with someone else:
1. **Only the original uploader** (requires tracking ownership
   separately from a grant).
2. **Anyone who currently has access** — the simpler rule, since every
   permission row already looks the same regardless of when it was
   granted.

## Decision
Option 2 throughout: a lightweight `user_id` stand-in, delivered via
middleware and a `ContextVar`, and "anyone with access can share
further" for the grant endpoint. Retrieval is filtered by an explicit
SQL join against a new `document_permissions` table, applied *before*
ranking and the `LIMIT`, not after.

## Reasoning
Deferring to item 14 was rejected for the same reason MCP's minimal
API key was chosen over waiting for full auth: a fake `user_id`
invented now is the same shape of thing whether it exists a week early
or as the first chunk of this feature, and waiting would delay real
functionality without making anything more genuine.

Middleware was chosen over `Depends()` specifically because it needed
to cover MCP too, and MCP tools aren't FastAPI routes — they can't use
route-level dependency injection. Wrapping the whole app the same way
`correlation_id_middleware` already does meant MCP inherited identity
enforcement automatically, no special-casing per entry point, the same
reasoning `ADR-017` already used for why MCP was mounted onto the
existing app rather than run standalone.

"Anyone with access can share further" was chosen over ownership
tracking as the smaller, honest option for this pass — the
`document_permissions` table has no concept of an owner today, only a
grant, and adding one would be new scope, not a refinement of what
already exists. The trade-off (a second person, once granted, can go
on to share with a third without the original uploader's involvement)
is accepted deliberately, not overlooked.

Filtering happens inside the SQL query itself — a join against
`document_permissions`, evaluated before `ORDER BY`/`LIMIT` — for the
same reason ADR-012's hybrid-search candidate pool was fixed to avoid
truncation before merging: filtering *after* ranking risks silently
returning fewer results than requested, or none, even when plenty of
accessible chunks existed just outside an unfiltered top-N.

## Consequences
- New files: `app/models/document_permission.py`
  (`DocumentPermission`, `GrantAccessRequest`, `GrantAccessResponse`),
  `app/repositories/permission_repository.py` (`grant_access` —
  idempotent via `ON CONFLICT DO NOTHING`, not check-then-insert, to
  avoid a race between two concurrent grants for the same pair —
  and `has_access`). `app/core/middleware.py` gained `user_id_middleware`
  and `get_current_user_id()`, mirroring the correlation ID pattern,
  plus a `PUBLIC_PATHS` exemption so Swagger UI stays browsable.
- **A missing `X-User-Id` is rejected outright with a 401** — unlike a
  correlation ID, which is safe to invent when absent, a user ID can't
  be guessed without breaking every permission check built on top of
  it.
- **Found live, not by reading the code:** FastAPI applies middleware
  in reverse registration order — the *last* one registered becomes
  *outermost*. `correlation_id_middleware` had to be registered last,
  not first, so it wraps `user_id_middleware` and still stamps a
  correlation ID even on a 401 rejection, which the project's own
  `CLAUDE.md` rule requires on every response.
- **A scope addition made mid-session, not originally planned:**
  rejected requests are now written to the audit log
  (`action="access_denied"`) — raised after a direct discussion of
  whether "nothing happened, so nothing to log" was the right call for
  a security-relevant event, not just a routine one. Uses the same
  `resource_id = correlation_id` convention `query_made` already
  established, since a bare rejected request has no other natural
  resource to name.
- **The audit log's `user_id` column, present since `ADR-008` but
  never populated**, is now filled in on every `document_upload`,
  `query_made`, and `permission_granted` entry — a gap that existed
  silently until this feature gave it something real to record.
- Uploading a document auto-grants the uploader access, unconditionally,
  *before* the ingestion `try` block — so it survives regardless of
  whether the document ends up `ready`, `failed`, or `pending_review`.
- **Two real bugs found live while wiring retrieval-time filtering,
  both from the same root cause — a new permission check breaking a
  path that reads the same data through a different function:**
  (1) `DocumentGraphService.build_references`, which searches *every*
  document at ingestion time to build cross-document reference links,
  crashed against the now-required `user_id` parameter — fixed with a
  separate, explicitly-named `find_by_keyword_unrestricted`, since
  reference-building is a system-level fact about documents, not a
  user-facing retrieval that should be permission-scoped to the
  uploader. (2) `get_first_chunk_text` — the function powering
  graph-context snippets — had **no permission filter at all**, a real
  gap where a user could receive content from a document they were
  never granted access to, as long as some document they *could* see
  happened to reference it. Fixed with the same join every other
  retrieval path uses. Neither bug was visible from reading
  `_retrieve_node` alone; both surfaced only once the feature was
  actually exercised end to end.
- Verified live, fully: a document owner gets a correct answer; a
  second user with no grant gets "I don't know" for the exact same
  question; granting that user access makes the same question succeed;
  and every document uploaded before this feature existed is now
  correctly invisible to everyone, including its own uploader, until
  explicitly re-granted — a real, expected consequence flagged before
  it was ever observed, not a surprise afterward.

## Scale, cost, and on-call reality
The core lesson this feature's own bugs demonstrated: there is no
single central gate that protects all chunk access in this system.
Every function that reads chunk content needs its own explicit
permission check — adding one to `find_similar_chunks` protects
exactly `find_similar_chunks`, nothing else. A future feature that
reads chunks through yet another new path (a future admin export
tool, a future analytics query) would need this same join applied
deliberately again; it does not inherit protection automatically. That
is a real, recurring on-call and code-review burden this design
accepts rather than eliminates.

"Anyone with access can share further" has a real, unbounded-sharing
risk at scale: a document granted to one person can, in principle, be
re-shared indefinitely with no way for the original uploader to see or
stop it, since there's no ownership concept to fall back to. Acceptable
for a single-tenant learning project; not something to carry into a
real multi-tenant deployment without adding ownership tracking first.

The permission join adds a real, permanent cost to every single
retrieval query, forever — not a one-time migration cost. At scale,
`document_permissions` needs an index on `(user_id, document_id)` (the
existing unique constraint already provides one) to keep this join
cheap; without it, every question asked would pay a full table scan on
top of the existing vector/keyword search cost, on every request.

The identity model itself remains the largest named limitation:
`X-User-Id` is entirely self-asserted, with nothing verifying a caller
actually is who they claim. That's the same honest trade-off MCP's
shared secret already accepted — proportionate for a project with no
real users yet, and exactly the gap build-order item 14 exists to
close later.
