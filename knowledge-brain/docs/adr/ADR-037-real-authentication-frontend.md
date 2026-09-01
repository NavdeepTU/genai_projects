# ADR-037: Real authentication — the frontend half

## Status
Accepted. Completes the pair with ADR-036 — backend session-cookie auth is
now actually usable from the UI, not just from `curl`.

## Context
ADR-036 gave the backend real, password-verified sessions and made every
REST endpoint reject the old self-asserted `X-User-Id` header outright.
That session deliberately left the frontend untouched: it kept sending the
same hardcoded header, so every page broke — Dashboard, Documents, Query,
Analytics, and Admin all failed to load anything. This session builds the
other half: login and signup pages, and switching every existing frontend
call from the dead header to the real session cookie.

## Options considered

**How the browser gets hold of a session cookie at all:**
1. **Relay the backend's own `Set-Cookie` header verbatim** through the
   Next.js route handler that proxies the login call.
2. **Issue a fresh cookie, owned by this app**, carrying the same token
   value the backend generated, with attributes chosen for this app's own
   environment.

**How pages get protected:**
1. **A single, edge-level gate** (Next.js's `proxy.ts`, formerly called
   "middleware") doing a full, database-backed validity check on every
   route.
2. **A cheap, edge-level presence check** (does *a* session cookie exist at
   all) plus a **real, database-backed check** wherever a page actually
   fetches its data — the same two-layer shape ADR-036's
   `user_id_middleware` already uses on the backend.
3. **No edge-level check at all** — rely entirely on each page's own data
   fetch to reject an unauthenticated request.

**Whether to build a signup page this session, or leave account creation
`curl`-only** (as the README already documented): built both — the user's
own call, made explicitly rather than assumed either way.

**How the login/signup forms actually talk to the backend:**
1. **Same-origin Next.js route handlers**, called via `fetch` from a
   Client Component — the exact pattern this project already uses for file
   upload and asking a question.
2. **Server Actions** — Next.js's newer, officially-recommended mechanism
   for form submissions, with less boilerplate and built-in pending-state
   handling.

## Decision
A fresh, app-owned cookie (option 1.2), the two-layer cheap-check-then-
real-check shape (option 2.2), both a login and a signup page, and
same-origin route handlers over Server Actions (option 4.1) — the user's
own explicit choice, made to keep one consistent pattern across the app
rather than introduce a second, newer mechanism on top of everything else
being new this session.

## Reasoning
Relaying the backend's `Set-Cookie` header verbatim was rejected because
that header's attributes (particularly its implicit origin binding) were
shaped for a server-to-server response, not for the browser's actual
relationship to this app. Every call to the backend already goes through
this app's own server — never directly from the browser — so nothing
requires the browser to hold the backend's literal cookie at all. It only
needs to hold *some* cookie, carrying the same opaque token, scoped
correctly to this app's own origin. Issuing a fresh cookie is not just
simpler, it's the more correct move: this app's route handler reads the
token out of the backend's response and calls `cookies().set()` itself,
with `secure`/`sameSite`/`maxAge` chosen for *this* app's environment,
not inherited from a response context the browser was never actually part
of.

A full database check on every single route inside `proxy.ts` was
rejected on Next.js's own explicit guidance: Proxy runs on every request,
including prefetches, so a real backend round-trip there would mean
paying that cost far more often than necessary, and Next's docs name this
directly as an anti-pattern. No edge-level check at all was rejected for
the opposite reason: it would mean every protected page pays for a full
render pass before discovering it has no real caller, and a first-line
gate for the obvious case (no cookie sent at all) is nearly free to add.
The two-layer shape — proxy.ts checking *presence*, each page's own fetch
(via the already-existing `lib/api.ts`/`lib/server-api.ts` calls)
checking *validity* — was chosen because it's the correct cost trade-off
*and* because it mirrors something already understood from the backend:
`user_id_middleware` is one central choke point checking real validity,
and `require_admin` layers a second, narrower check on top for the one
route that needs it. Proxy.ts and each page's data-fetch are the same
shape, just split across a network boundary.

Server Actions were rejected specifically because they're a second,
different pattern for the same underlying job — "get data from a form to
the backend" — that this codebase already solves with route handlers for
file upload and the query box. Introducing a second pattern now would
have meant learning it *and* the actual session mechanics in the same
pass; keeping one consistent pattern kept the session focused on what it
was actually about.

## Consequences
- New pages: `app/login/page.tsx`, `app/signup/page.tsx` — thin Server
  Component wrappers that call `getCurrentUser()` and redirect to `/` if
  already logged in, around `components/login-form.tsx` /
  `signup-form.tsx`, the actual Client Component forms.
- New route handlers: `app/api/auth/login/route.ts`,
  `.../signup/route.ts`, `.../logout/route.ts` — same same-origin-proxy
  pattern as the existing upload/status/query routes. Signup chains a
  second, server-to-server call to `/auth/login` right after account
  creation succeeds, so a new user lands already logged in rather than
  filling the login form immediately after the signup form — a small,
  deliberate UX call, not an architectural one.
- New `lib/auth.ts`: `getCurrentUser()` (cached per-render via React's
  `cache()`, backed by a real `GET /auth/me` call — not just cookie
  presence), plus the cookie read/write/clear helpers.
- New `proxy.ts` (not `middleware.ts` — Next.js 16 renamed the
  convention; same mechanism, new name and export). Exempts `/login` and
  `/signup`; everything else needs a session cookie present or gets
  redirected.
- `lib/api.ts` split into two files, forced by a real build failure, not
  a style preference: Turbopack's Server/Client boundary check operates
  at the *file* level, so a Client Component (the Query page) importing
  anything from a file that also imports `next/headers` (even a function
  it never calls) fails to build. Client-safe exports (`postQuery`,
  shared types) stayed in `lib/api.ts`; every server-only call
  (`getDashboard`, `getAnalytics`, `getAdmin`, `getDocuments`) moved to a
  new `lib/server-api.ts`.
- `lib/config.ts`'s `CURRENT_USER_ID` placeholder removed entirely; every
  existing route handler and `lib/server-api.ts` call now forwards the
  real session cookie instead of the old header.
- `components/navbar.tsx` now takes a `user` prop (fetched once in
  `app/layout.tsx`): shows the caller's email and a working logout
  control when logged in, a plain "Log in" link when not, and only shows
  the Admin nav item when `user.is_admin` is true.
- A real, structural side effect, not a bug: documents uploaded through
  the frontend before this session were permission-granted to the old
  `"dev-user"` string, which was never a real account. No real session
  can ever produce that identity again, so those old rows became
  permanently unreachable through the app — verified and cleaned up by
  hand against the local database (a real `DELETE`, run by the user
  directly, not by Claude — permanent deletion is never done on the
  user's behalf regardless of how it's requested). Re-uploading under a
  real account is the only path forward; nothing automatically migrates
  old `document_permissions` rows to a new identity.
- A live setup gap, not a code bug: the very first live signup attempt
  failed with a genuine `UndefinedTableError` — ADR-036's `users`/
  `sessions` tables had never actually been created against the local
  database, since running `scripts/create_tables.py` is a step the user
  runs by hand and it simply hadn't happened yet. Caught immediately by
  testing live in the browser, not assumed away.
- A `/code-review` pass after the initial build found and fixed six real
  issues, none of them security-critical but all genuine: a login route
  that could return `200` with no session actually established if the
  backend's `Set-Cookie` header ever came back unusable; an upload
  status-poll `setInterval` that kept firing after a `401` instead of
  clearing itself; a logout button with no error handling that could get
  permanently stuck on a network failure; and three duplication issues
  (the session-cookie-plus-gateway-secret header pair copy-pasted across
  four call sites, the `Set-Cookie`-extraction logic duplicated between
  login and signup, and `proxy.ts` hardcoding its own copy of the cookie
  name instead of sharing one source of truth) consolidated into shared
  helpers (`lib/auth.ts`'s `backendAuthHeaders`/`applySessionFromResponse`,
  and a new dependency-free `lib/constants.ts` so `proxy.ts` can share
  the cookie-name constant without pulling in `next/headers`). One
  duplication finding — `signup-form.tsx` being structurally near-
  identical to `login-form.tsx` — was deliberately left as-is: two
  concrete call sites with small real differences is exactly the case
  where a shared abstraction costs more than the duplication it removes.
- Verified live in the browser, twice — once after the initial build,
  again after the `/code-review` fixes: signup creates an account and
  auto-logs in; every protected page loads real, cookie-authenticated
  data; the Admin page correctly `403`s a non-admin account with the
  updated error message; a real question round-trips through the query
  proxy end to end; logout clears the session and blocks further access;
  logging back in works independently of signup's auto-login path; and
  visiting `/login` while already authenticated correctly bounces back to
  `/` without looping. Type-check, lint, and a full production build all
  pass clean after every change.

## Scale, cost, and on-call reality
Every protected page now pays one real network round trip
(`GET /auth/me`, via `getCurrentUser()`) in `app/layout.tsx` to render the
navbar's user info, on top of whatever round trip the page's own data
fetch already makes — React's `cache()` prevents that from becoming *two*
calls to the backend within the same render, but it's still a cost this
app didn't pay before real auth existed. At this project's actual
traffic that's invisible; it's the direct, accepted cost of proving
identity on every request rather than trusting a header for free. There
is still no "return to where you were" redirect after login — landing
on `/login` from a deep link always sends you to `/` afterward, not back
to the page you wanted, a small UX gap named but not closed this
session. And the frontend inherits every gap ADR-036 already named on
the backend unchanged: no rate limiting on the login form, and a fixed
7-day session with no sliding renewal or a "log out everywhere" control.
