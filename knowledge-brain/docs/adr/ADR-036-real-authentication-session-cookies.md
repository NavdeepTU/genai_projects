# ADR-036: Real authentication — email/password with server-side session cookies

## Status
Accepted. Backend only — frontend wiring is deliberately deferred to a
separate future session (see Consequences).

## Context
Every request in this system has, until now, carried its identity as a
plain `X-User-Id` header that the caller sets to whatever it likes.
Nothing checks it against a password, a token signature, or any other
proof — it's identity without authentication, a trade-off this project
named and accepted early (ADR-007, and again explicitly in ADR-034 when
the admin allowlist was built on top of the same unproven header). That
trade-off was proportionate while this was a single-developer learning
project with no real users. Build-order item 14, "auth, multi-tenancy,
and production hardening," is where it stops being proportionate.

This ADR covers real authentication only. Multi-tenancy — row-level
isolation between separate companies' data — is a related but separate
decision, explicitly scoped out of this pass and left for its own
future ADR.

## Options considered

**For the authentication model itself:**
1. **Server-side session cookies** — log in once, the server creates a
   `Session` row and hands the browser a random opaque token in an
   `httponly` cookie. Every later request looks that token up against
   the database. The server can revoke a session at any moment just by
   deleting the row.
2. **JWT (JSON Web Tokens)** — log in once, the server hands back a
   signed token containing the user's identity directly. Later requests
   are verified by checking the signature, not by a database lookup —
   no server-side session state at all.
3. **An external identity provider** (e.g. Azure AD B2C) — hand the
   entire login flow to a managed service and trust the token it
   returns.

**For password storage:**
1. **Argon2id**, via `argon2-cffi` used directly.
2. **bcrypt**, the long-standing conventional default, most commonly
   reached for via the `passlib` wrapper library.

## Decision
Server-side session cookies (option 1), with passwords hashed using
Argon2id via `argon2-cffi` used directly, not through `passlib`.

## Reasoning
JWT was rejected specifically because it trades away the thing this
pass exists to teach: a JWT's whole point is that the server *doesn't*
need to hold session state, so choosing it here would mean skipping the
actual mechanics of hashing, sessions, and revocation rather than
learning them. It would also be the wrong tool for what this project
needs regardless of the learning goal — nothing here demands stateless,
cross-service token verification at the scale JWT is built for, and a
JWT can't be revoked before it expires without adding back the exact
server-side state it was chosen to avoid. An external identity provider
was rejected for the same reason as JWT, one level further removed: it
hands the entire mechanic to a managed service, leaving nothing to
actually build or understand. Session cookies were chosen because they
are the option that requires — and therefore teaches — the real parts:
a password hash that must never be reversible, a token that must never
be guessable, and a server that is the sole, revocable source of truth
for who is logged in.

Argon2id was chosen over bcrypt on the strength of a live check, not
inherited habit: OWASP's Password Storage Cheat Sheet promoted Argon2id
to its top recommendation in a 2024 update, with bcrypt as the
fallback when Argon2id isn't available — and it isn't the unavailable
case here. `argon2-cffi` was used directly instead of through `passlib`
after confirming `passlib` is genuinely unmaintained (last released in
2020, confirmed broken on current Python) — a real, current finding,
not an assumption carried over from how tutorials usually teach this.

Two design details follow directly from the "prove it, don't invent
it" goal:
- The session's `token` (the actual secret sent to the browser) is a
  different value from the session row's own `id` — `id`s appear
  routinely in this project's log lines, and leaking one must never be
  equivalent to leaking a working login. `token` is generated with
  `secrets.token_urlsafe(32)`, not `uuid4()` or anything derived from
  predictable state, because it needs to be unguessable, not merely
  unique.
- A failed login returns the identical error whether the email doesn't
  exist or the password is wrong. Distinguishing the two would let an
  attacker use the login form to discover which email addresses have
  accounts at all.

MCP was deliberately left on its existing shared-API-key model
(ADR-017), not migrated to session cookies. An MCP client isn't a
browser and has no natural way to hold or send a cookie the way this
scheme assumes — folding it in would be new scope, not a migration of
existing scope, and the existing shared-secret trust model already
matches ADR-017's own reasoning for why MCP doesn't need the same
protection REST endpoints do.

## Consequences
- New tables: `users` (`app/models/user.py`) and `sessions`
  (`app/models/session.py`), added to both `scripts/create_tables.py`
  and `tests/conftest.py`'s model-import lists so
  `Base.metadata.create_all` picks them up — this project still has no
  migration tool (ADR-027's gap, unchanged), so the user runs
  `scripts/create_tables.py` by hand against both local Docker Postgres
  and, later, Azure Postgres.
- New repositories: `UserRepository`, `SessionRepository`
  (`app/repositories/`) — direct DB access only, no hashing or
  business logic.
- New service: `AuthService` (`app/services/auth_service.py`) — the
  only place in the codebase that ever touches a real password, hashed
  or plain. Raises `EmailAlreadyRegisteredError` and
  `InvalidCredentialsError`, both handled by the API layer.
- New router: `app/api/auth.py` — `POST /auth/signup`,
  `POST /auth/login` (sets the session cookie), `POST /auth/logout`
  (clears it), `GET /auth/me`. Each state-changing action writes to the
  append-only `audit_log` table, matching this project's existing
  Enterprise Requirement 6 pattern for `document_upload`, `query_made`,
  and `permission_granted`.
- `app/core/middleware.py`'s `user_id_middleware` — the central change.
  It now branches on path: requests under `/mcp` still trust
  `X-User-Id` unchanged; every other request must present a valid,
  unexpired session cookie, looked up against the database, or the
  request is rejected with `401` before it reaches any route. `/auth/
  signup` and `/auth/login` are exempted from this check, since they're
  how a caller gets a session in the first place.
- `app/core/admin_auth.py`'s `require_admin` now checks the new
  `User.is_admin` column instead of the `ADMIN_USER_IDS` allowlist
  introduced in ADR-034 — the "small slice of real auth, pulled
  forward" that ADR-034 named is now the real thing, so the env-var
  allowlist was removed from `config.py` and `.env` rather than left
  behind as a second, dead admin check.
- New setting: `environment` (`dev`/`staging`/`prod`, reusing the same
  three values as the Terraform environment tag) — decides whether the
  session cookie is marked `secure`. A `secure` cookie is silently
  dropped by the browser over plain `http`, which is exactly how this
  app runs locally, so `dev` leaves it off; `staging`/`prod` run `https`
  end to end and get it on.
- New tests: `tests/test_auth.py` (signup, duplicate email, correct and
  incorrect login, logout, expired-session rejection, unknown-user
  lookup) and a rewritten `tests/test_admin.py` (`require_admin` now
  exercised against real `User` rows instead of a mocked allowlist).
  Suite: 30 → 39 passing. Verified the app still imports cleanly and
  the full suite passes after every change.
- **Not built this pass, by design:** the frontend still sends the old
  `X-User-Id` header and has no login/signup UI — it will not
  successfully authenticate against this backend until a separate,
  already-agreed future session wires it up (login/signup pages, the
  Next.js Route Handler forwarding the cookie, every existing
  `lib/api.ts` call, route protection, a logout control). Multi-tenancy
  and the rest of item 14's "production hardening" are equally out of
  scope here.

## Scale, cost, and on-call reality
Every session lives for a fixed 7 days from creation (`SESSION_LIFETIME`
in `app/models/session.py`) with no sliding renewal and no refresh
token — a user is simply logged out after a week regardless of
activity. That's a deliberate simplicity choice for this pass, not a
scale limit, but it's the first thing to revisit if "stay logged in
while actively using the product" becomes a real requirement.
`SessionRepository.get_user_by_token` runs a join on every single
authenticated request now, where the old scheme did no database work
at all to establish identity — at this project's current traffic this
is invisible, but it's a real, permanent per-request cost that a
JWT-based scheme wouldn't pay, which is the direct trade for JWT's own
lost revocability. There is no rate limiting on `/auth/login` yet, so
nothing in this pass slows down a password-guessing script beyond
Argon2id's own deliberately-slow hashing cost — that's a gap worth
naming now and closing before this system could honestly be called
production-hardened, alongside the still-open `ADMIN_USER_IDS`-shaped
question of what happens once there are enough real users that "who's
an admin" can't just be eyeballed in a database row.
