# ADR-016: LLM-as-judge evaluation harness with dedicated fixture documents

## Status
Accepted

## Context
The query pipeline has grown genuinely complex — hybrid search,
reranking, a LangGraph retry loop, and now graph context from Neo4j,
five external dependencies feeding into one answer. There has been no
systematic way to know whether all of that is actually working well
together; `docs/ARCHITECTURE.md` already named this gap honestly
("the only backstop is a human noticing an answer looks wrong"). This
is build-order item 9. A related but distinctly different idea — a
real-time safety/guardrails check on every live answer — came up in
the same conversation and was deliberately split out as its own item
(16), since it's a different shape of tool: a per-request gate, not an
offline quality measurement.

## Options considered
For where the evaluation harness's known-answer test corpus comes from:
1. **Whatever documents currently exist in the dev database.** No new
   ingestion needed, but not reproducible — the dev database's contents
   change as other features get manually tested (this exact session
   left behind throwaway "ticket"/"billing" test documents from
   verifying the Neo4j feature).
2. **A fully separate eval database**, the same pattern already used by
   the pytest test suite (`knowledge_brain_test`).
3. **Dedicated, purpose-written fixture documents, ingested into the
   same dev database as everything else**, looked up by filename before
   ingesting so re-running eval never creates duplicates.

For how faithfulness and correctness get judged:
1. **One combined LLM call** returning both scores in a single JSON
   response — cheaper, one round trip.
2. **Two separate, focused calls** — one per judgment.

## Decision
Option 3 for the corpus; two separate calls for judging.

## Reasoning
Option 1 (ad-hoc dev database contents) was rejected for the reason
above: an eval run's results need to mean the same thing every time
it's run, and a corpus that silently drifts as unrelated features get
manually tested defeats that. Option 2 (a fully separate database) was
considered, specifically because it's the pattern already established
for pytest, but rejected as unnecessary weight for this case — the goal
was isolating a small, known *set of documents*, not isolating an
entire database connection and schema. Dedicated fixtures, idempotently
ingested into the same database real traffic uses, gets the same
reproducibility without a second database to stand up and maintain.

Two separate judge calls were chosen over one combined call because
they're checking genuinely different things — is the answer grounded,
versus does it match the reference facts — and combining them risks the
model conflating the two judgments in one response. The cost of two
calls instead of one was accepted as the smaller risk.

## Consequences
- New `eval/` directory, parallel to `tests/` and `scripts/` — not part
  of the running FastAPI app, an on-demand tool: `eval/fixtures/`
  (three small, purpose-written, topically distinct documents),
  `eval/dataset.json` (six test cases: question, reference answer,
  which fixture it should come from), `eval/judge.py` (two LLM-as-judge
  functions, own circuit breaker `openai_eval_judge`), `eval/run_eval.py`
  (the runner).
- Two small additions to existing files, not new concerns bolted on
  sideways: `DocumentRepository.get_document_by_filename` (idempotent
  fixture lookup) and `RetrievalService.run_query` (returns the full
  pipeline state, not just the answer string — `answer_question` is now
  a thin wrapper around it). Both are genuinely reusable, not
  eval-only hacks: `run_query` in particular is the kind of thing any
  future caller needing more than the final answer text would also
  want.
- Both judge functions default to `False` on a missing key or an
  unparseable response — fail closed, not fail open. A broken judge
  call registers as "this failed," not as a silent pass, which matters
  specifically for a tool whose entire purpose is catching problems.
- Retrieval correctness is checked by comparing `chunk.document_id`
  against the fixture's actual ID — not by string-matching text, same
  "reference real state, don't reimplement the check" principle used
  throughout this project's test suite.
- Verified live, not just that it runs: all 6 test cases passed on all
  three dimensions (retrieval, faithfulness, correctness) against the
  real pipeline, real Postgres, real Neo4j, real OpenAI, and real
  Voyage.
- Hit Voyage's real 3-requests-per-minute free-tier limit running all 6
  cases back-to-back — a real, permanent feature this time, not a
  throwaway script, so it was actually fixed: a 20-second pace between
  cases (skipped before the first, so a single-case run isn't
  needlessly slowed).

## Scale, cost, and on-call reality
This is a manual, on-demand tool today, not wired into CI — nothing
runs it automatically on a commit or a pull request yet. That's a real,
named gap: the harness can catch a regression, but only if someone
remembers to run it. Wiring it into GitHub Actions is natural future
work (build-order item 12's territory), not done here.

Cost-wise, one full eval run is not free: six test cases, each making a
real embedding call, up to two searches, a rerank call, a generation
call, and now two separate judge calls — roughly 6-8 LLM/vendor calls
per test case, 36-48 for a full run. Small at six cases, but a real
number that would need watching if the dataset grows meaningfully
larger, especially against Voyage's unpaid rate limit, which is already
the binding constraint at this tiny scale.

Worth naming honestly, since it's a real, known limitation of the
LLM-as-judge pattern generally, not specific to this implementation:
the judge is itself an LLM call, which means it can be wrong or
inconsistent between runs, the same way the system being tested can.
Eval scores from this harness are a strong signal, not a mathematical
proof — a real trade-off of using a model to grade a model, accepted
here because there's no cheaper way to judge open-ended text for
faithfulness or semantic correctness, but worth being able to say
plainly rather than presenting eval results as unquestionable ground
truth.
