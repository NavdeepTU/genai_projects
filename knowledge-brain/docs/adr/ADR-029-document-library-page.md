# ADR-029: Document Library page — a missing endpoint, server-side fetching, and a static-rendering trap

## Status
Accepted, verified live in the browser and against the real backend.

## Context
The Document Library was chosen as the first real page to build, since
uploading is a user's very first action, matching the order the backend
itself was built in (ingestion before retrieval). Before any frontend
design work started, a real gap surfaced: the backend had no way to
*list* documents at all — only `POST /documents/upload` and
`POST /documents/{id}/access` existed.

## Decision

**1. Built `GET /documents`, permission-filtered from the start.**
`DocumentRepository.list_documents_for_user` joins `Document` to
`DocumentPermission` and filters by the caller's `user_id`, the same
join pattern `find_by_keyword`/`find_similar_chunks` already use —
deliberately, not incidentally: this project's own `ADR-019` already
named the exact risk of a new data-reading path skipping the ACL
another path already enforces. Returns `status`, `uploaded_at`, and
`pii_detected` alongside the filename — not just filenames — since
`CLAUDE.md`'s own spec for this page names "processing status" and "PII
warning badge" as the literal requirement, not speculative scope.

**2. Frontend fetches server-side, avoiding CORS entirely.** The
backend has no CORS configuration, which would block a browser calling
it directly from a different origin (`localhost:3000` vs `localhost:8000`).
Rather than add `CORSMiddleware` to the backend, `app/documents/page.tsx`
is a Next.js Server Component that fetches server-to-server — a request
between two servers, not a browser cross-origin request, so CORS never
applies. Chosen over configuring CORS because it needed no backend
change at all for something driven by a temporary, pre-auth identity
placeholder.

**3. A temporary, explicit auth placeholder.** With no real login yet,
`lib/config.ts` hardcodes `CURRENT_USER_ID = "dev-user"`, sent as
`X-User-Id` on every request — the same honest, self-asserted-identity
pattern the backend has accepted project-wide since document-level ACL
first shipped, now extended to the frontend rather than inventing a
different placeholder scheme.

## A real incident: this page would have silently frozen in production
Verified live, the empty state rendered correctly and the page carried
no visible bugs. But the Next.js dev overlay reported "Route: Static" —
worth investigating rather than dismissing, since a "library" page's
entire purpose is showing frequently-changing data. Checked the actual
caching docs for this project's specific configuration (Cache Components
is not enabled, confirmed in `next.config.ts`) rather than the newer,
inapplicable Cache Components docs: by default, Next.js caches any
`fetch()` reachable before a request-time API (`cookies()`, `headers()`,
`searchParams`) is used — and `getDocuments()` uses none of those. In a
production build, this page would have been rendered *once* at build
time and served as a frozen snapshot to every visitor indefinitely,
never showing a newly uploaded document without a full rebuild. Dev
mode hides this completely — "pages are always rendered on-demand" in
dev, per the docs — so this would never have surfaced from local testing
alone. Fixed with `export const dynamic = "force-dynamic"`, and
confirmed directly: the dev overlay's route classification changed from
"Static" to "Dynamic" after the fix.

## Reasoning
Both real findings this session came from checking actual behavior and
actual current documentation, not from code review or assumption — the
same standard this project has held Azure work to since ADR-020. The
missing-endpoint gap was caught by checking `documents.py`'s real routes
before designing anything, not by assuming the page could be built
first and wired up after. The static-rendering trap was caught by
questioning a debug-overlay label that looked cosmetic, not by trusting
that a clean-looking empty state meant the whole page was correct.

## Consequences
- Every future page reading frequently-changing, per-user data (Query
  history, Analytics, Admin) needs the same explicit
  `dynamic = "force-dynamic"` treatment — this isn't a one-off fix,
  it's a pattern to apply by default to any page whose data isn't
  meant to be shared identically across all visitors indefinitely.
- Dynamic rendering and document-level ACL are independent mechanisms,
  not substitutes for each other: dynamic rendering guarantees fresh
  data on every request, ACL guarantees only the right *subset* of that
  data comes back. Freshness without authorization would leak; authorization
  without freshness would just be correctly-scoped but stale.
- `dev-user` is a real, temporary limitation carried over from the
  backend's own accepted trade-off (self-asserted identity, no real
  auth yet) — every page built before item 14 (real auth) exists will
  need this same placeholder swapped out eventually, tracked as a
  known, deferred piece of work rather than hidden inside one file.

## Scale, cost, and on-call reality
The CORS-avoidance decision (server-side fetching) is the right call
for this project's shape today, but it has a real limit: it only works
for data a Server Component can fetch *before* rendering. The upcoming
upload flow needs real-time interactivity (drag-and-drop, a file
picker, progress feedback) that can't happen from a Server Component
alone — that will force a genuine choice next: either add CORS to the
backend for that one interactive path, or proxy the upload through a
Next.js Route Handler (another server-to-server hop, same CORS-avoidance
logic, extra latency). Worth deciding deliberately when that chunk
starts, not defaulting into whichever is easiest in the moment.

The static-rendering trap is a genuine production-readiness lesson,
independent of this project's scale: at real traffic, a "static"
misclassification wouldn't just show stale data to one visitor — it
would serve the *same* frozen snapshot to every visitor from a CDN edge
cache, at global scale, until a redeploy. Catching this at zero users is
strictly cheaper than catching it after a real launch.
