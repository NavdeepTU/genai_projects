# ADR-043: Streamed answer generation

## Status
Accepted.

## Context
Build-order item 19, the last untouched item in the original build order,
and Enterprise Requirement 11. Every answer up to this point was fully
blocking: `RetrievalService`'s LangGraph ran retrieval through generation
and the output guardrail as one call, and `/query` returned the whole
answer in a single JSON response only once every step had finished. The
model takes the same total time to finish generating an answer either
way — this feature doesn't make that faster. What it changes is how long
the user waits before seeing anything at all (time-to-first-token, TTFT),
which is the entire point of streaming.

This was also the first time this project touched Server-Sent Events
(SSE) — chosen over WebSocket per the original build spec, since this is
one-way server-to-client output with no need for a bidirectional
channel, and it passes through Azure API Management with less friction
than a WebSocket upgrade.

## Options considered

**How streaming interacts with the existing output guardrail:**
The non-streaming pipeline runs one moderation check and one injection
check against the *complete* answer before ever showing it. Streaming
can't wait for a complete answer to exist.
1. **Moderation per sentence as it's produced; injection only after the
   full answer is known, and only able to retract, not prevent** — the
   chosen approach. A sentence is checked and released as its own
   `chunk` event; the injection judge (which needs the complete text to
   judge whether the answer was hijacked by something smuggled into
   retrieved document text) can only run once streaming finishes, so a
   flagged answer means telling the client to erase what it already
   showed.
2. Drop the injection check entirely for streamed answers, since it
   can't run incrementally. Simpler, but silently removes a guardrail
   category (retrieved-content prompt injection) that every other path
   in this project still enforces.

**New endpoint vs. modifying `/query`:**
1. **A genuinely separate `/query/stream` route** — the chosen approach.
   `/query` is untouched and stays the one entry point MCP and the
   evaluation harness use. Before deciding this, I checked the actual
   installed `mcp` package's streaming support rather than assuming: it
   supports progress notifications, not content streaming, so there was
   nothing for MCP to gain from a streaming endpoint anyway.
2. Add a `stream: bool` flag to the existing `/query` route. One fewer
   route, but forces every caller (including MCP and the eval harness)
   to reason about a response shape that only the browser UI ever needs.

**How to create a streaming seam in a pipeline that was one blocking
LangGraph call end to end:**
1. **Shorten the compiled graph itself to stop one step before
   generation, and call generation as a plain method afterward** — the
   chosen approach. `build_query_graph` now ends at `graph_context →
   END`; `_generate_node` and `_output_guardrail_node` are no longer
   graph nodes, just methods `run_query` calls directly. Both the
   blocking path and the streaming path call the exact same shortened
   graph, then diverge only for that last step.
2. Build a second, parallel pipeline for streaming that re-implements
   retrieval, reranking, the weak-reranking retry loop, and domain
   routing outside the graph. Avoids touching the existing graph at all,
   but duplicates real control flow (the retry loop, domain dispatch)
   that would need to be kept in sync by hand forever after.
3. Thread a `streaming: bool` flag through `QueryState` itself, so the
   same graph either calls blocking generation or short-circuits before
   it depending on the flag. Keeps one graph, but makes every node in it
   aware of a concern — how the caller wants the answer delivered — that
   has nothing to do with what any of those nodes actually do.

## Decision
Moderation checks each sentence as it streams; the injection check runs
once on the complete answer and can retract already-shown text. Real
token-by-token streaming exists only behind a new `POST /query/stream`
route — `/query` is unchanged. The LangGraph pipeline itself was
shortened to end at `graph_context`, with generation and the output
guardrail demoted to plain method calls that both `run_query` (blocking)
and the new streaming endpoint call after the same graph invocation.

A question needing more than one domain (ADR-040) doesn't get real
token streaming — each domain still generates its own full answer, then
synthesis merges them, so the merged text is sent as a single `chunk`
event instead of token by token. This was a deliberate scope decision,
not a limitation of the design: the common case (a single domain) is
what streaming is worth the complexity for.

## Reasoning
Accepting retract-after-the-fact for injection, instead of dropping the
check, was chosen because this project already treats "checked and
clean" and "no signal at all" as different claims everywhere else (the
input guardrail, the non-streaming output guardrail, domain
classification's fallback) — dropping the check for streamed answers
specifically would have made streaming the one path in the system with
a real, unlabeled gap in coverage.

A separate endpoint over a flag on `/query` was chosen because nothing
about MCP or the eval harness's actual use of the answer benefits from
streaming — confirmed by reading the real `mcp` package rather than
assuming, which is what actually resolved this decision rather than
leaving it a guess.

Shortening the graph itself, rather than building a parallel pipeline or
threading a flag through the state, was chosen because it's the only
option of the three where the blocking and streaming paths are
*structurally* guaranteed to behave identically up to the seam — there
is no second copy of the retry loop or domain-dispatch logic to drift
out of sync, and no per-node conditional to reason about. This was
verified, not assumed: the full pre-existing test suite (94 tests) was
run immediately after this refactor and passed unchanged, and again
after the later `FederatedRetrievalService` refactor that built
`prepare_for_generation`/`synthesize_and_finalize` on top of it.

## Consequences
- `app/services/query_graph.py`: the compiled graph now ends at
  `graph_context → END`; `generate` and `output_guardrail_check` are no
  longer nodes.
- `app/services/retrieval_service.py`: new `_prepare_for_generation`
  (runs the shortened graph); `run_query` calls it, then calls
  `_generate_node`/`_output_guardrail_node` directly — behaviorally
  identical to before, confirmed by the unchanged test suite.
- `app/services/generation.py`: new `stream_answer`, reusing
  `generate_answer`'s existing circuit breaker (same underlying OpenAI
  dependency; a failure should count against the same breaker, not a
  redundant one).
- `app/services/streaming.py` (new): `stream_checked_answer` — the
  sentence-buffering, per-sentence moderation, and retract-after-the-fact
  injection logic described above. Both its own checks treat their own
  unavailability as an immediate block, the same "no signal is not the
  same as clean" rule this project applies everywhere else, but with no
  second check to fall back on the way the non-streaming path has.
- `app/services/federated_retrieval_service.py`: new `prepare_for_generation`
  (the seam the streaming route needs for both single- and multi-domain
  questions), `synthesize_and_finalize` (the multi-domain merge, extracted
  from `_run_federated` for reuse), and public `build_sources_and_confidence`.
  A real bug was caught and fixed mid-build here: `MultiPrepared` initially
  carried only the answerable domain runs, but `synthesize_and_finalize`
  needs the full `succeeded` list too (to report a block reason when
  nothing is answerable) — fixed by having `MultiPrepared` carry both,
  with a regression test added specifically for the case that would have
  broken.
- `app/api/query.py`: `resolve_conversation` and `save_turn_and_refresh_cache`
  extracted from the route body so `/query/stream` can reuse the exact
  same conversation-resolution and turn-persistence logic rather than a
  second copy of it.
- `app/api/query_stream.py` (new): the `POST /query/stream` route.
  Retrieval, reranking, ACL filtering, and federated retrieval all
  complete before the response is created; only the final generation
  step streams. Emits `chunk`, `ttft`, `retract`, `done`, and `error`
  events, each a Pydantic model (`StreamChunkEvent`, `StreamTtftEvent`,
  `StreamRetractEvent`, `StreamDoneEvent`, `StreamErrorEvent` in
  `app/models/query.py`) rather than a raw dict.
- Frontend: `lib/api.ts`'s new `streamQuery` hand-parses SSE frames from
  a `fetch()` response body via `ReadableStreamDefaultReader`, since the
  native `EventSource` API can't send a POST body. A new
  `app/api/query/stream/route.ts` proxy pipes the backend's SSE body
  through untouched (`response.body` forwarded directly) rather than
  buffering it into JSON, which would have defeated the purpose of
  streaming one proxy hop before the browser. `query-chat.tsx` renders
  chunks live as they arrive and erases shown text on a `retract` event.
  `postQuery`, its `QueryResponse` type, and the old `/api/query` proxy
  route were deleted once nothing called them any more.
- Tests: 94 → 108 backend (`stream_answer`'s empty-choices guard and
  open-circuit failure; `stream_checked_answer`'s full event matrix —
  success, a flagged sentence retracting immediately, moderation
  unavailable, generation failing mid-stream, injection flagging after
  the answer was shown, injection unavailable, a trailing sentence with
  no closing punctuation; `prepare_for_generation`'s single- and
  multi-domain branches; the `MultiPrepared` regression test above).
  17 → 26 frontend (`query-chat.tsx`'s live-chunk rendering and retract
  behavior; a new `lib/api.test.ts` testing `streamQuery`'s SSE parsing
  directly — a frame split across two network reads, multiple frames in
  one read, a multi-byte UTF-8 character split mid-character across a
  read boundary, and the 401/error-body handling).
- A `/code-review` pass after the initial build found six real, confirmed
  issues, all fixed the same session: the audit-log calls inside the SSE
  generator had no error handling (a DB failure there would abruptly
  truncate the stream with no `error`/`done` event ever sent); the
  audit log's `duration_ms` measured a different span of work than
  `/query`'s definition of the same field, which would have skewed the
  Analytics page's average-response-time metric for every streamed
  query — fixed with two separate timers (one for TTFT, one matching
  `/query`'s pipeline-only span); the SSE payloads were raw dicts
  instead of Pydantic models; `event_stream()` had no docstring or
  return type; `FederatedResult.duration_ms` was silently left at `0.0`
  in the multi-domain streaming path, breaking `synthesize_and_finalize`'s
  own stated contract; and `postQuery`/`/api/query` were confirmed dead
  and removed. None of these were caught by the tests written during the
  initial build — the same lesson ADR-042 already named: tests that pass
  are not the same claim as tests that would have caught what was
  actually broken.
- Verified live, twice: once after the initial build (a real streamed
  answer through the browser, confirmed via network inspection that the
  request to `/api/query/stream` stayed genuinely pending rather than
  resolving instantly; and, unplanned but useful, a real block via the
  injection guardrail — a test document already in the corpus, tripped
  by an unrelated follow-up question, confirmed both the successful and
  the blocked answer saved correctly through the new
  `save_turn_and_refresh_cache` path), and again after the `/code-review`
  fixes, confirming the corrected `duration_ms` and Pydantic events still
  produced a correct, working stream end to end.

## Scale, cost, and on-call reality
A streamed single-domain answer now costs one moderation call per
sentence instead of one call for the whole answer — a real, felt cost
that scales with answer length, accepted because the alternative
(buffering the whole answer before checking it) would defeat the reason
this feature exists. The injection check's retract-after-the-fact
design is a genuine, different security posture from every other path
in this project: it's the one place in the system where unchecked model
output can be visible to a user, even briefly, before a check has a
chance to withdraw it. This isn't hypothetical — it was exercised for
real during this session's own live verification.

The multi-domain path gets none of this feature's benefit: same total
latency as before, now just delivered as one large SSE `chunk` instead
of a plain JSON body. If cross-domain questions become common enough
that this matters, real per-domain streaming with an interleaving or
turn-taking strategy would be a follow-up feature, not something this
design accounts for today.

FastAPI's dependency lifecycle for `db`/`graph_session` was verified
against the actual installed FastAPI source (not assumed) to survive
the full `StreamingResponse` body iteration — a classic footgun
(a DB session closed out from under a still-streaming generator) this
feature could have hit silently under real concurrency if that had gone
unchecked.
