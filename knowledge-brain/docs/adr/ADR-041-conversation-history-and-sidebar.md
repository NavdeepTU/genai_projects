# ADR-041: Conversation history, storage, and the sidebar

## Status
Accepted.

## Context
Build-order item 18's full spec (Enterprise Requirement 10) covers three
things together: a conversations/turns schema in Postgres, Redis-cached
recent turns, and an LLM condensing step that rewrites a follow-up like
"what about the other one" into a standalone question before it enters
retrieval. The user's own request for this session was narrower and
explicit: build storage and a resumable sidebar now, with less focus on
condensing — that work is coming in a later session. Before today,
nothing about a conversation persisted anywhere; the Query page held its
transcript in React state only, gone on reload (a deliberate scope cut
already named in ADR-031, not a gap discovered now).

## Options considered

**Scope for this session:**
1. **Storage + sidebar + resume only, condensing deferred** — the user's
   own explicit choice.
2. Build the full item 18 spec in one pass, including condensing.

**Redis, given condensing is out of scope this session:**
1. **Defer Redis to next session** — the user's own choice. Redis's only
   real job in the spec is caching recent turns so condensing doesn't
   pay a database round trip per message; with no condensing step to
   serve, there's nothing for it to do yet.
2. Stand up Redis now anyway (docker-compose service, connection
   wiring, a circuit breaker) so it's ready and already tested before
   next session's condensing logic needs it.

**How a conversation gets its sidebar title:**
1. **Truncate the first question** — the user's own choice. Free,
   deterministic, no added latency on the first turn of a conversation.
2. Ask an LLM to generate a short title — a cleaner label, at the cost
   of a new LLM call on every conversation's first question.

**Where sources and domains are stored per turn:**
1. **JSONB / a plain string array on the `turns` row itself**, matching
   `AuditLog.extra_data`'s own precedent — written once, read back
   whole, never queried by an individual field.
2. Normalized tables (a `turn_sources` join table, etc.) — real
   relational structure, for data nothing in this feature ever needs to
   query by its own fields.

**When a new conversation actually gets created:**
1. **Only after the answer comes back successfully** — a failed
   attempt (a 503 from the retrieval pipeline) never leaves an empty,
   answerless conversation sitting in the sidebar.
2. Create it immediately, before running the query, and accept that a
   failed first question leaves an empty thread behind.

**How resuming actually works on the frontend:**
1. **A real route per conversation** (`/query/[conversationId]`, with
   `/query` itself meaning "new"), so a reload or a shared link resumes
   the same thread for real.
2. Keep a single `/query` route and hold the active conversation only
   in client-side state — simpler, but a reload loses it, which
   defeats the actual point of "resume any time."

## Decision
Storage and a resumable sidebar only, this session — no condensing yet.
Redis deferred to the session that actually builds condensing. Titles
are a plain truncation of the first question. Sources and the domains a
turn used are stored as JSONB/array columns on the turn row directly,
matching `AuditLog`'s own established shape. A conversation is created
in Postgres only once its first answer actually comes back. Resuming is
a real Next.js route per conversation, not client-side state alone.

## Reasoning
Deferring condensing was the user's own scope call, and Redis followed
directly from it: building Redis now, with no condensing step to read
from it, would mean standing up a whole new piece of infrastructure —
docker-compose service, connection settings, a circuit breaker — with
nothing exercising it until next session. That's exactly the kind of
built-ahead-of-need infrastructure this project avoids elsewhere; Redis
gets introduced when it has a real job to do, not before.

Plain truncation over an LLM-generated title was chosen because a
sidebar label is cosmetic — it doesn't need to be *good*, it needs to
be there, and it needs to not cost anything. Paying for a generation
call on every single conversation's first turn, forever, to make a
sidebar entry look slightly nicer, wasn't judged worth it.

JSONB storage for sources/domains reuses `AuditLog.extra_data`'s exact
precedent rather than introducing a new pattern: this data is written
once when a turn is created and read back whole when a conversation is
resumed — nothing in this feature ever needs to search across turns by
a specific source's filename or a specific domain. A normalized table
would add real schema and join complexity for a query this system
never runs.

Deferring conversation creation until the answer actually succeeds
avoids a specific, real annoyance: without it, someone whose first
question in a new thread happened to hit a 503 (both search backends
down, or a saturated circuit breaker) would find an empty, nameless
conversation sitting in their sidebar forever, with no way to tell it
apart from a conversation that simply hasn't been asked anything yet.

A real per-conversation route, not client-side-only state, was the only
choice that actually satisfies what was asked: "start from any of the
past conversations any time" means a reload, a bookmark, or a link sent
to yourself has to land back in the same thread. Client state alone
can't do that — it's gone the moment the tab closes. This did mean
extracting the existing single-file Query page's chat logic
(`QueryChat`) into its own component so it could be shared between the
"new" and "resume" routes, rather than duplicating the transcript UI in
two places.

## Consequences
- New `app/models/conversation.py`: `Conversation` (id, user_id, title,
  created_at, updated_at) and `Turn` (id, conversation_id,
  raw_question, condensed_question, answer, sources JSONB, confidence,
  domains_used, correlation_id, created_at) tables, plus their Pydantic
  response models. `condensed_question` is stored equal to
  `raw_question` for now — a placeholder column, not a half-built
  feature; next session's condensing work fills it in for real.
- New `app/repositories/conversation_repository.py`:
  `create_conversation`, `add_turn` (also bumps the conversation's
  `updated_at`, so the sidebar's most-recently-active ordering reflects
  real activity), `list_conversations_for_user`,
  `get_conversation_for_user` (returns `None` identically whether the
  conversation doesn't exist or belongs to someone else, the same
  indistinguishable-404 shape `get_document_for_user` already uses —
  simpler here, since a conversation has exactly one owner and no
  sharing model the way documents do).
- New `app/api/conversations.py`: `GET /conversations` (list, for the
  sidebar), `GET /conversations/{id}` (detail with turns, for
  resuming).
- `app/api/query.py`: resolves an existing `conversation_id` (if given)
  *before* calling `FederatedRetrievalService.run_query` — a bad or
  someone-else's id fails fast with a 404 rather than after paying for
  a full retrieval pass. `QueryRequest` gained an optional
  `conversation_id`; `QueryResponse` gained `conversation_id` back.
- Frontend: `frontend/components/query-chat.tsx` (the extracted,
  shared chat UI, now generalized to accept `initialConversationId`
  and `initialTurns`), `frontend/components/conversation-sidebar.tsx`
  (the sidebar, plus a mobile Sheet-based equivalent, reusing the same
  list-rendering logic), a new `frontend/app/query/layout.tsx`
  (server-fetches the conversation list once, wraps both routes below
  it), `frontend/app/query/page.tsx` (now just renders `QueryChat` with
  no initial state), and a new
  `frontend/app/query/[conversationId]/page.tsx` (fetches one
  conversation's turns server-side, with its own `not-found.tsx` for a
  bad or unauthorized id). MCP's `ask_knowledge_base` is untouched —
  conversation tracking lives entirely at the route layer, one level
  above `FederatedRetrievalService`, which never changed.
- Tests: 7 new backend tests (`ConversationRepository` — creation,
  turn storage, the `updated_at` bump, user-scoped listing and
  ordering, the stranger-gets-`None` permission check, turns returned
  in order). 8 new frontend tests (`ConversationSidebar` rendering;
  `QueryChat` rendering pre-existing turns from props, and sending the
  right `conversation_id` — `null` for a new conversation, the real id
  for a resumed one). Backend suite: 70 → 77 passing. Frontend: 15 → 23.
  One incidental fix along the way: jsdom has no `scrollIntoView`
  implementation at all, which this project's own auto-scroll-to-latest
  behavior needs — polyfilled once in `vitest.setup.ts` as a no-op,
  since any future component using it would hit the same gap.
- Verified live end to end: asked a first question with no
  `conversation_id` — got one back, confirmed it appears in `GET
  /conversations`. Asked a follow-up using that id — confirmed both
  turns land in `GET /conversations/{id}`, in order. Confirmed a
  nonexistent or someone-else's `conversation_id` returns 404 on both
  the detail endpoint and `/query` itself. Drove the actual frontend in
  a browser: a fresh question created a conversation, updated the URL,
  and appeared in the sidebar without a full page reload; navigating
  directly to that URL (simulating a reload) resumed the same
  transcript; "New conversation" correctly returned to a blank state;
  an invalid conversation URL rendered the custom not-found page
  rather than a generic error.

## Scale, cost, and on-call reality
This feature adds no new external dependency and no new LLM call — it's
pure Postgres reads/writes around a pipeline that already ran. The real,
deliberately deferred cost is condensing itself: every follow-up
question today still pays for a full retrieval pass, even an obvious
one like "what about the other one," which a short, cheap rewrite could
substitute for once that step exists. `router.refresh()` firing after
every single question re-fetches the entire conversation list
server-side, not just the one conversation that changed — fine at
today's per-user conversation counts, but a user with hundreds of
conversations would refetch all of them on every message; a real
fix (returning just the affected conversation and patching client
state) wasn't built this pass. Conversations have no delete or rename
capability yet — once created, a conversation exists in the sidebar
permanently. And this feature inherits, rather than introduces, the
project's standing "no migration tool" gap: `conversations` and `turns`
were new tables, not new columns on an existing one, so this particular
session didn't need a hand-run `ALTER TABLE` — but the next schema
change that does will hit the exact same manual process as every prior
one.
