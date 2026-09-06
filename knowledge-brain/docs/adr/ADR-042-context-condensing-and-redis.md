# ADR-042: Context condensing for follow-up questions, and Redis

## Status
Accepted.

## Context
Build-order item 18's other half. ADR-041 built conversation storage and
a resumable sidebar, but deliberately left the raw follow-up question
going straight into retrieval unrewritten — "what about the other one"
would fail exactly as it always had, since nothing looked at prior
turns to figure out what "the other one" meant. Redis was also
deliberately deferred in that same session: its only real job in the
build spec is caching recent turns for condensing to read, and with no
condensing step to serve, there was nothing for it to do yet. This
session builds that condensing step, and — since it now has a real job
— introduces Redis for the first time in this project.

## Options considered

**When condensing runs:**
1. **Always, on every follow-up** — the user's own explicit choice.
   Simple and predictable: every question in an existing conversation
   pays for one condensing call, whether or not it actually needed
   rewriting.
2. Smart detection — an LLM (or heuristic) first judges whether a
   question is already self-contained, only condensing when it looks
   like a real follow-up. Cheaper on average, but adds its own judgment
   call that can be wrong in both directions.

**Redis, now that condensing exists:**
1. **Introduce it for real** — a genuine `redis.asyncio` connection, its
   own circuit breaker, a new docker-compose service. The user's own
   choice, directly following from last session's own reasoning: it now
   has an actual consumer.
2. Skip Redis, read recent turns from Postgres on every follow-up.
   Simpler, but pays a database round trip on every single question in
   every conversation, forever — exactly what the build spec's Redis
   requirement exists to avoid.

**Where condensing sits relative to the existing input guardrail:**
1. **Condense first, then the pipeline's existing input guardrail
   checks the condensed text** — the user's own choice. The guardrail
   node already lives inside `FederatedRetrievalService`'s graph, not
   something the route calls separately; condensing before entering the
   pipeline means zero changes to that graph. Cost: a jailbreak-style
   follow-up pays for one condensing call before being caught, instead
   of being caught immediately.
2. Check the guardrail on the raw text first, separately, before
   condensing runs. Catches a bad follow-up as fast as a bad first
   question, but means either duplicating guardrail logic outside the
   graph or running the moderation/jailbreak checks twice (raw, then
   condensed) on every follow-up — doubling that cost on the common
   case to shave time off the rare one.

**Where the condensing orchestration logic itself lives:**
1. **A service function (`get_effective_question`,
   `update_recent_turns_cache` in `app/services/condensing.py`)** —
   this project's own established rule, that routes stay thin and
   testable logic lives in a service, applied here the same way ADR-031
   already applied it once. I initially wrote this directly in
   `app/api/query.py` and caught it myself before writing a single
   test — there was nowhere to point a test at it sitting in a route.
2. Leave it inline in the route. Simpler to write once, but untestable
   without a running HTTP server, which this project doesn't use
   anywhere else.

## Decision
Condense every follow-up, always — no smart-detection step. Redis is
now real infrastructure, holding each conversation's last 3 turns.
Condensing happens before the pipeline runs, so the existing input
guardrail (unchanged) checks the condensed text, not the raw one. All
of the orchestration — resolving which question should actually be
asked, and refreshing the cache afterward — lives in
`app/services/condensing.py`, not the route.

## Reasoning
Always-condense was chosen for the same reason this project has
repeatedly chosen "simple and predictable" over "smart but occasionally
wrong" elsewhere (plain-truncated conversation titles over an
LLM-generated one, free-text domains over a managed taxonomy): a
detection step is itself a judgment call that can fail in two
directions — condensing a question that didn't need it (wasted cost,
same failure mode as always-condensing) or skipping one that did (a
silent correctness failure, worse than a wasted LLM call). Paying the
cost every time is honest about what it costs, with no hidden failure
mode.

Introducing Redis now, not before, was the direct consequence of
deferring it last session specifically until it had a real job —
condensing needing the last 3 turns on every follow-up is exactly the
"read the same small thing over and over, fast" pattern Redis exists
for, and Postgres already sitting right behind it as a fallback means
there was no risk in adding a cache with nothing yet depending on it
being infallible.

Condensing before the guardrail, rather than checking the raw text
separately first, was chosen because the guardrail already lives as a
graph node inside `FederatedRetrievalService` — pulling it out to run
twice, or duplicating its logic at the route layer, would have doubled
the moderation/jailbreak LLM cost on every single follow-up to shave
latency off catching a comparatively rare jailbreak attempt slightly
sooner. The condensed question is what actually enters retrieval and
generation regardless, so it's also the more meaningful thing for the
guardrail to be judging.

Moving the orchestration logic into `condensing.py` rather than leaving
it in the route wasn't a decision made in the abstract — it was caught
mid-build, the same way the eval harness's `RetrievalService` bug and
the domain-badge key collision were caught earlier this project: by
actually trying to do the next thing (write a test) and finding it
couldn't be done cleanly where the code sat.

## Consequences
- New `app/services/condensing.py`: `condense_question(raw_question,
  recent_turns: list[RecentTurn])` (an LLM call, own circuit breaker,
  same shape as `query_rewriting.py` — a genuinely different mechanism
  from that rewrite, though: query rewriting is a retry aid, generation
  always uses the true original question; condensing's output *becomes*
  the real question for both retrieval and generation, since raw text
  like "what about the other one" has no independent meaning to answer
  at all). `get_effective_question(raw_question, conversation)` is the
  single place that decides whether to condense at all — a brand-new
  conversation (`None`) always passes through unchanged.
  `update_recent_turns_cache` appends the newest turn and trims to the
  configured window (`condensing_context_turns`, default 3) after an
  answer comes back.
- New `app/core/redis_cache.py`: a small `get`/`set` wrapper around
  `redis.asyncio`, its own circuit breaker, a 24-hour TTL per
  conversation's cached turns. Deliberately catches broadly (not just
  `CircuitOpenError`) on both read and write — a lesson pulled forward
  from ADR-040's own honestly-named gap: a raw connection error on
  Redis's very first call, before its breaker has even opened, must
  still fail open rather than crash the request it's attached to.
- New `RecentTurn` Pydantic model (`app/models/conversation.py`)
  replaces a plain `{"question", "answer"}` dict at every module
  boundary this data crosses — the raw-JSON boundary is now only where
  it belongs, at the actual Redis serialization edge.
- `app/repositories/conversation_repository.py`: `get_conversation_for_user`
  already eager-loads a conversation's full turn list for the ownership
  check; condensing's Postgres fallback reuses that directly
  (`conversation.turns[-N:]`) instead of a second query, and the tiebreaker
  gap review found in `Turn`'s ordering (no secondary sort key) is fixed
  on the relationship itself, not a since-removed standalone query
  method.
- `app/core/config.py`: new `redis_url` (required, no default, matching
  how every other connection string in this project is configured) and
  `condensing_context_turns` (defaults to 3).
- `docker-compose.yml`: a new `redis` service, mapped to host port 6380
  (matching Postgres's own 5433-instead-of-5432 pattern, avoiding a
  clash with any system-wide Redis).
- Tests: 24 covering `condense_question`'s empty-choices guard,
  `get_effective_question`'s full decision table (no conversation,
  no prior turns, a cache hit, a cache-shape validation failure falling
  back to the conversation's own turns, the circuit-open and
  generic-error fallbacks), `update_recent_turns_cache`'s seed/append/trim
  behavior, and `redis_cache.py`'s fail-open behavior directly — a
  deliberate departure from this project's usual "don't unit-test thin
  external-service wrappers" convention, since this one isn't an LLM
  wrapper, it's a resilience mechanism whose entire job is failing open
  correctly. Backend suite: 84 → 94 passing (18 written alongside the
  feature itself, 6 more added after `/code-review` found gaps in the
  first pass — see below).
- A `/code-review` pass after the initial build found seven real,
  confirmed issues, all fixed the same session: the `choices[0]`
  IndexError and the `json.loads` exposure named above, the raw-dict
  convention violation, the missing ordering tiebreaker, the redundant
  Postgres query, a docstring in `Turn` that had gone stale the moment
  this diff started writing real condensed values, and a missing
  docstring on `_cache_key`. None were caught by the tests written
  during the initial build, since none of those tests exercised the
  actual failure edges being wrong at all — writing tests that pass
  isn't the same claim as writing tests that would have caught what
  was actually broken.
- Verified live, twice over: first end to end through a real multi-turn
  conversation — "how many vacation days," then four genuine follow-ups
  in a row ("does it require Python?", "and databases?", "what skill is
  preferred most?"), each condensed correctly using the real prior
  turns. Then again after the `/code-review` fixes, to confirm the
  refactor (passing the full `Conversation` object instead of just its
  id, removing the redundant repository method) didn't change observed
  behavior — a fifth follow-up in the same conversation still condensed
  and answered correctly.

## Scale, cost, and on-call reality
Every follow-up in every conversation now pays for one additional LLM
call, unconditionally — a real, felt cost, not a hypothetical one,
directly following from "always condense" over smart detection. Redis
removes what would otherwise be a Postgres round trip on every one of
those calls, but adds a new external dependency this project didn't
have before, with its own circuit breaker and its own honestly-named
failure mode (documented and tested: a corrupted or unreachable cache
degrades to Postgres, never a crash). The condensing LLM call itself
has the same structural limit named for the injection judge in ADR-039
and the domain classifier in ADR-040: it's an LLM, and there's no
formal guarantee it always produces a faithful rewrite rather than a
subtly wrong one — a wrong condensed question would search and answer
confidently against the wrong thing, with nothing today that would
notice. Not solved this session, and not unique to this feature.
