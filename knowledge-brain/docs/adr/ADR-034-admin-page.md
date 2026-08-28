# ADR-034: The Admin page — a minimal allowlist, not real RBAC

## Status
Accepted.

## Context
Build-order item 13's fifth and final planned page. CLAUDE.md's spec
names four things: tenant management, user permissions, document
access control settings, and an audit log viewer. Checking what
backend support already existed before designing anything — the same
discipline every prior frontend page in this project has applied —
found a bigger gap than any previous page: this system has no concept
of "admin" at all. Every page built so far scopes data to the caller's
own — their documents, their queries, their audit entries. An admin
page, by definition, shows *every* user's data at once. That's not
more of the same pattern; it's a real, first-time increase in what a
single request can expose, and it needed its own explicit decision
before any code was written, not a default either way.

Tenant management has nothing behind it: this system has no
multi-tenancy concept yet (build-order item 14, untouched) — there is
no "tenant" to manage. Document access control already supports
granting (`POST /documents/{id}/access`) but not revoking. An audit
log viewer needs genuinely new backend work: every existing read
(`get_recent_queries_for_user`, `get_query_entries_for_user`) is
scoped to one user's own `query_made` entries; nothing reads across
every user or every action type yet.

## Options considered
For gating the admin routes:
1. **A lightweight, explicit allowlist** — a small set of user IDs
   read from configuration, checked before any admin route responds.
2. **No gating at all** — consistent with this project's already-
   accepted "identity without authentication" trade-off everywhere
   else, but a real escalation here specifically, since every other
   page only ever exposes the caller's own data regardless of that
   trade-off.

For tenant management, permissions, and the audit viewer:
1. **Ship what's real now** (permissions read-only, a real cross-user
   audit log), **honest placeholder for what isn't** (tenant
   management), **defer what's cheap-but-separate** (revoking access)
   to a later, explicit pass — matching the user's own stated intent
   ("basic page first, add functionality later").
2. Build all four fully now, including a from-scratch tenant model and
   a revoke endpoint, to match the spec exactly in one pass.

## Decision
A lightweight admin allowlist (`ADMIN_USER_IDS`, comma-separated,
empty by default so nobody is an admin until deliberately configured),
enforced by a new `require_admin` FastAPI dependency attached at the
router level. Permissions and the audit log are real and read-only for
this pass; tenant management is an honest placeholder; revoking access
is deferred, not built.

## Reasoning
No gating was rejected specifically because this page is different in
kind from every other page built so far, not just bigger. The Query,
Dashboard, and Analytics pages all read data already scoped to the
caller by the underlying query itself — leaving them open was
proportionate to a project with no real users yet, since a caller
could only ever see their own information regardless. An admin page
that shows every user's documents, permissions, and full activity
history to anyone who sets any `X-User-Id` header is a materially
different exposure, and closing it costs almost nothing: one
dependency function, one environment variable, attached once at the
router level so every current and future admin route inherits it
automatically. This mirrors the exact trade-off this project already
made for MCP's shared secret (ADR-017) — a small, explicit, deliberate
slice of real authorization pulled forward, not the full system (item
14) built early, and not skipped either.

Tenant management stayed a placeholder for the same reason retrieval
accuracy and cost-per-query did on the Dashboard and Analytics pages:
there is no real data model behind it, and building one "just for this
page" would mean quietly implementing a meaningful piece of item 14's
actual scope under this feature's name, rather than as its own
deliberate, later decision.

Revoking access was named as a real, cheap, self-contained addition —
structurally the mirror of `grant_access`, a `DELETE` instead of an
`INSERT ... ON CONFLICT DO NOTHING` — but deferred anyway, because the
user's own framing ("basic page first, add functionality later")
already answered the question before it needed to be asked as a fork.

A related but separate gap surfaced in conversation after the page
shipped: documents flagged `pending_review` for PII have no reviewer
workflow at all — not even a way for an admin to see what triggered
the flag, since the extracted text and raw file bytes are both
discarded once `flag_for_review` runs, never persisted anywhere. Worth
naming precisely because it's not simply "add an approve button": any
real review workflow needs its own decision about where flagged
content lives long enough to review (Blob Storage for raw bytes, or
persisting extracted text at flag-time), and needs to itself be
admin-gated for the same separation-of-duties reason `require_admin`
exists at all — the uploader who created the risk shouldn't be the one
clearing it. Deliberately scoped out of this ADR, tracked as its own
future item.

## Consequences
- `app/core/config.py`: new `admin_user_ids: str = ""`.
- `app/core/admin_auth.py`: new `require_admin()`, a FastAPI dependency
  reading `X-User-Id` (via the existing `get_current_user_id()`) against
  the parsed allowlist, `403`s if absent.
- `app/repositories/audit_repository.py`: new `get_all_recent_entries` —
  the first read in this repository unscoped by user_id. Docstring
  explicit that it does no authorization itself; that's the caller's
  job via `require_admin`.
- `app/repositories/permission_repository.py`: new
  `list_all_permissions`, joined against `Document` for filenames —
  the permission-side equivalent, same "no authorization here" contract.
- `app/models/admin.py`, `app/api/admin.py`: new `GET /admin`, gated
  at the router level (`dependencies=[Depends(require_admin)]`) so
  every route added to this router later inherits the gate without
  needing to repeat it.
- Frontend: `frontend/app/admin/page.tsx` (Server Component,
  `dynamic = "force-dynamic"` from the start — a habit now applied
  automatically to every new data page since the Document Library
  session first found the gap live), reusing `ListCard` and `StatTile`
  from prior sessions — no new shared components needed this time,
  the first frontend page built entirely from already-extracted pieces.
  `admin/error.tsx` deliberately shows the real error message, unlike
  every other page's fixed generic one — a 403 ("you're not an admin")
  and a genuine server failure are different situations worth telling
  apart here specifically.
- New tests: `tests/test_admin.py` — `require_admin` allowed/rejected/
  empty-allowlist-locks-everyone-out, and both new repository methods
  confirmed to span multiple users, not just the caller. Test suite:
  25 → 30 passing.
- Verified live: the admin endpoint correctly returned `403` before
  `ADMIN_USER_IDS` was set locally, and real cross-user data (multiple
  real user IDs, multiple real action types) after — confirming the
  gate and the "spans every user" behavior aren't just unit-tested in
  isolation, but actually work together against the real database.

## Scale, cost, and on-call reality
The allowlist is a real, named limit, not full authorization: it
answers "is this caller allowed to use admin routes at all," nothing
finer — no per-action permissions, no read-only-vs-full-admin
distinction, no expiry, no audit trail yet on the *admin's own* actions
specifically (though every admin request still gets a correlation ID
and passes through the same middleware as everything else). At a
handful of trusted operators this is proportionate; it would need to
become real RBAC (item 14) before this system could honestly support
more than a small, known set of administrators. `get_all_recent_entries`
and `list_all_permissions` are both unbounded reads today — fine at
this project's current row counts, the same category of future cost
`get_query_entries_for_user`'s 5000-row cap (ADR-033) already named
for a different table; both would need real limits or pagination
before this page could be trusted against a much larger audit log or
permission table.
