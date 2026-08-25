# ADR-031: The Query page — synchronous answers, no conversation history

## Status
Accepted.

## Context
Build-order item 13's second planned page. CLAUDE.md's own frontend
spec for this page describes an answer that "streams in token-by-token
as it generates" and "a sidebar [that] lists past conversations so a
user can resume an old thread." Neither of those is actually buildable
today: token streaming is build-order item 19, with its own detailed
Enterprise Requirement (11) covering SSE transport, sentence-chunked
guardrail checks, and time-to-first-token tracking — none of which
exist yet. Conversation history is item 18, with its own Enterprise
Requirement (10) covering a conversations/turns schema, Redis-cached
recent turns, and context condensing for follow-up questions — also
nothing built. Both sit later in the build order than today's item.
Separately, the existing `/query` endpoint's response (`answer`,
`correlation_id` only) doesn't carry what the page also needs to show:
which documents an answer actually drew from, and how confident the
system is — data the LangGraph pipeline already computes internally
(`QueryState.reranked_chunks`, `top_relevance_score`) but never
returns past `RetrievalService.answer_question`'s plain string.

## Options considered
For how the answer appears on screen:
1. **Synchronous** — call `/query`, show a loading state, render the
   complete answer once the response arrives.
2. **A fake client-side typewriter effect** — get the complete answer
   back, then reveal it a few characters at a time with a timer,
   purely cosmetic.
3. **Build real SSE streaming now** — pull item 19 forward: a genuine
   token-by-token backend endpoint, then the page against it.

For conversation history:
1. **No sidebar, no persistence** — a plain scrolling transcript for
   the current page visit only, held in React state, gone on reload.
2. **Build real conversation storage now** — pull item 18 forward: a
   database schema, Redis caching, and a condensing step.

For exposing sources and confidence:
1. **Extend `QueryResponse`** with `sources` and `confidence`, sourced
   from data `QueryState` already has.
2. **A second endpoint** just for sources/confidence, called
   separately from the answer.

## Decision
Synchronous answers, no fake streaming. No sidebar or persisted
history — a single in-page transcript, lost on reload. `QueryResponse`
extended in place with `sources: list[QuerySource]` and `confidence:
float | None`, computed from the existing pipeline's own output, no
new computation added.

## Reasoning
Options 2 and 3 for streaming were both rejected, for different
reasons. The fake typewriter effect would look identical to real
streaming on screen while lying about the architecture underneath —
no SSE, no real time-to-first-token improvement, nothing item 19
actually requires — and would need to be quietly torn out and rebuilt
once item 19 is real, rather than extended. Building real SSE now
was rejected purely on build-order grounds: it's a full feature with
its own Enterprise Requirement, not a small addition to a page, and
CLAUDE.md is explicit that features aren't picked ahead of turn.
Synchronous costs nothing extra today and leaves a clean, honest seam
for item 19 to attach to later — the frontend's loading state already
covers the ">500ms shows a loading state" UX rule this project holds
to regardless of whether the wait is one round trip or a stream.

The same reasoning applied to conversation history: a real sidebar
needs real storage, Redis caching, and a condensing step to be
meaningful (a follow-up like "what about the other one" resolves
against stored prior turns) — none of that exists, and faking a
sidebar against nothing but client-side state would just be a UI shell
with no real feature behind it. A single-visit transcript still lets
someone ask several related questions in one sitting, which is most of
the day-to-day value, without pretending persistence exists.

Extending `QueryResponse` in place (over a second endpoint) was the
only real choice for exposing sources and confidence, since both
values already exist inside the exact same `QueryState` the answer
itself comes from — a second endpoint would mean re-running or
re-fetching the same pipeline result a second time, for no benefit.
`confidence` is typed `float | None`, not defaulted to `0.0`, because
`0.0` already means something specific elsewhere in this codebase
(`_rerank_safely`'s `reranker_unavailable` flag exists precisely so a
real low score is never confused with "no score was computed at all")
— reusing that same distinction here, rather than introducing a new
one, keeps "no real confidence available" honest at the API boundary,
not just internally.

## Consequences
- `app/models/query.py`: new `QuerySource` (`document_id`, `filename`,
  `chunk_text`); `QueryResponse` gains `sources` and `confidence`.
- `app/api/query.py`: switches from `RetrievalService.answer_question()`
  to `run_query()` to get the full `QueryState`; builds `sources` from
  `reranked_chunks`, deduping filename lookups per document via the
  existing unchecked `get_by_id` (permission was already enforced
  upstream, at retrieval, so no second check is needed here); sets
  `confidence = None` when `reranker_unavailable`, else
  `top_relevance_score`. MCP's `ask_knowledge_base` tool is untouched —
  it only ever needed the plain answer string, so `answer_question()`
  stays exactly as it was, no regression risk from this change.
- New frontend: `frontend/app/query/page.tsx` (a Client Component — a
  scrolling transcript, an input pinned at the bottom, per-turn
  loading/error states, an empty state before the first question),
  `frontend/app/api/query/route.ts` (a same-origin proxy, same pattern
  ADR-030 already established for uploads, so `BACKEND_GATEWAY_SECRET`
  never reaches client-side JavaScript for this client-triggered
  action either), and `postQuery()`/new types in `lib/api.ts`.
- Sources are shown per-chunk (up to 5, one per chunk actually used by
  generation), not grouped and deduplicated by document — a
  deliberately simple default, not a fork: it's literally what
  informed the answer, and multiple chunks from the same document can
  legitimately both matter.
- Verified live: a real question against real ingested documents
  (a plain `.txt` fixture and a real multi-page PDF) returned a
  correct answer, real per-chunk sources with real filenames, and a
  real confidence score (0.777, `high confidence` in the UI) — through
  both a direct `curl` against the backend and the frontend's own
  proxy route.

## Scale, cost, and on-call reality
This adds no new external dependency and no new query — it's strictly
returning more of what one existing pipeline run already computed. The
real, deliberately accepted cost sits in what's *not* built: without
item 19, a slow answer (a large context, a cold circuit breaker retry)
is a real, visible wait with nothing shown until the whole thing
resolves — acceptable at today's traffic and response times, a genuine
UX regression once real users hit slower, larger real-world documents.
Without item 18, every question pays the full retrieval pipeline's
cost even for what a human would recognize as an obvious follow-up
("what about the other one") — no condensing step exists yet to let a
short, cheap rewrite substitute for a full re-retrieval. Both gaps are
the same two features this ADR named and deliberately deferred, not
new ones discovered after the fact.
