# ADR-014: LangGraph query pipeline with a relevance-gated retry loop

## Status
Accepted

## Context
The query pipeline (`RetrievalService.answer_question`) was a fixed,
linear sequence: embed the question, run hybrid search, merge with RRF,
rerank, generate. Every request ran the exact same steps in the exact
same order, regardless of what came back — there was no way for the
pipeline itself to notice "these results are weak" and do anything
about it. The build order calls this out specifically as "multi-step
reasoning" (item 5): the ability for the query flow to branch or loop
based on what it actually finds, not just execute a straight line.

## Options considered
For detecting "the results are weak enough to do something about,"
three approaches were considered:
1. **Check if reranking returned zero chunks.** The original plan —
   simple, and matched the architecture we sketched out before writing
   any code.
2. **A similarity floor inside `find_similar_chunks` itself,** filtering
   out chunks past some cosine-distance cutoff before they ever reach
   reranking.
3. **Voyage's own `relevance_score` from the rerank response,**
   thresholded after reranking runs.

## Decision
Option 3 — a threshold (`0.4`) on the top reranked chunk's
`relevance_score` — but only after Option 1 was built first, tested
live, and found to not actually work.

## Reasoning
Option 1 was implemented first, per the original architecture. Testing
it live (not just reading the code) showed it doesn't work: asking a
completely unrelated question ("the price of milk on Jupiter") against
the real database never triggered the retry, because `find_similar_chunks`
has no relevance floor — it always returns the *closest* chunks by
distance, however irrelevant, as long as the table isn't empty. An
"empty results" check can only ever fire when there's *no data at all*,
which isn't the failure case that matters.

Between the two real fixes, Option 3 was chosen over Option 2 because
the reranker is a more precise judge of relevance than raw cosine
distance — that's the entire reason reranking exists in this pipeline
(ADR-013) — and it required no new query logic, just using a number
Voyage already computes and `reranking.py` was previously discarding.
The `0.4` threshold itself was picked empirically, not guessed: a
genuinely relevant match scored `0.914` against the real dev database,
while two different irrelevant questions both scored `~0.28–0.29` — a
wide, clean gap, with `0.4` sitting comfortably inside it. That gap was
only measured against four chunks, though, so the threshold is tracked
as something to re-check once there's real document variety (see
`docs/PROGRESS.md`).

One more deliberate scope decision: this ADR covers only the
retrieval-quality loop (bad search results → rewrite → retry). A
different, more advanced loop — checking whether the *generated
answer* is actually grounded in its context, after generation — was
explicitly discussed and deferred, likely to pair with the evaluation
harness (build order item 9) rather than be built standalone now.

## Consequences
- Two new files: `query_rewriting.py` (an isolated LLM call with its
  own circuit breaker, `openai_query_rewrite`, kept separate from
  generation's breaker so a rewriting outage can't masquerade as a
  generation outage) and `query_graph.py` (the `QueryState` shape and
  the compiled graph).
- `answer_question` is now a thin wrapper: build the state, hand it to
  a compiled LangGraph graph, return `result["answer"]`. The actual
  step logic moved into five methods on `RetrievalService`
  (`_retrieve_node`, `_rerank_node`, `_rewrite_node`, `_generate_node`,
  `_should_retry`) — all of them reuse the exact same
  `_find_similar_chunks_safely` / `_find_by_keyword_safely` /
  `_rerank_safely` helpers hardened in ADR-012 and ADR-013, unchanged.
  Nothing about the existing partial-failure or reranker-fallback
  behavior was rewritten to make this work.
- `_should_retry` skips the retry entirely — not just declines it, skips
  attempting it — when reranking itself is unavailable
  (`reranker_unavailable`), as opposed to when reranking succeeded but
  found nothing good. A vendor outage isn't a bad-phrasing problem;
  rewriting the question and searching again can't fix an unreachable
  API, and would almost certainly just hit the same open circuit a
  moment later, for no benefit.
- New setting: `retrieval_relevance_threshold` (`0.4`), not hardcoded —
  applying a lesson already flagged in an earlier code-review pass
  about tunable numbers belonging in `Settings`.
- `MAX_RETRIES = 1`, a hard cap, not a setting. Explicitly *not* raised
  for higher traffic (see below) — this is a correctness bound (stop
  looping forever), not a tuning knob.
- A real testing mistake surfaced while verifying this: patching
  `RetrievalService._rewrite_node` on the class *after* constructing a
  `RetrievalService` didn't work, because the graph is built once in
  `__init__` and captures a bound-method reference at that moment —
  patching the class afterward doesn't reach an already-built graph.
  The fix was patching the module-level `rewrite_query` function
  instead, which every node looks up fresh on each call. Worth
  remembering for any future LangGraph testing in this codebase.

## Scale, cost, and on-call reality
A single query that *doesn't* trigger the retry makes 4 external calls:
one embedding call, one rerank call, one generation call, plus two
database queries (vector + keyword search, sequential — same
single-`AsyncSession` constraint as ADR-012). A query that *does*
trigger the retry roughly doubles that: a second embedding call, a
second round of both searches, a second rerank call, plus the rewrite
call itself — six external AI vendor calls instead of three, for one
user-facing request. That's a real, non-trivial cost multiplier worth
knowing, not just a "sometimes it loops once" hand-wave.

This is exactly why `MAX_RETRIES` should not scale up with traffic,
which came up directly while designing this: at 10x load, both circuit
breakers (reranking's and rewriting's) will trip open more often purely
from call volume. Raising the retry cap in response would make that
worse, not better — every retry is more load on the exact vendors
already struggling, which is the retry-storm risk ADR-012 already
reasoned its way out of once. The correct lever at higher scale is
tuning the circuit breakers' own thresholds to scale with traffic (a
fixed "3 failures in 60 seconds" is tuned for dev-level call volume, not
production), not retrying more.

On-call-wise, this pipeline now has a failure mode that's easy to miss
without knowing to look for it: because the retry is silent — the user
just gets an answer, with no signal in the API response about whether a
retry happened — the *only* place this is currently visible is the
correlation-tagged log lines inside `_rewrite_node`. There's no metric
yet for "retry rate" as a number an on-call engineer could watch on a
dashboard; today it's log-grep-only. That's an acceptable gap now, at
zero production traffic, but would need a real metric before this ran
for real users.
