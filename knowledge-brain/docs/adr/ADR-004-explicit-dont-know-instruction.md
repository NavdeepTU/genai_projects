# ADR-004: Explicitly instruct the LLM to say "I don't know" rather than guess

## Status
Accepted

## Context
When retrieval finds no genuinely relevant chunks (empty database, or a
question the documents don't cover), the generation step still receives
whatever chunks were closest — possibly irrelevant ones — plus the
question, and has to decide how to respond.

## Options considered
1. **Rely on the model's default behavior** — trust a well-behaved LLM to
   naturally recognize when context doesn't answer the question.
2. **Explicitly instruct the model, in the system prompt, to say it
   doesn't know rather than guess when the context doesn't contain the
   answer.**

## Decision
Explicitly instruct the model (Option 2).

## Reasoning
An LLM's default tendency, absent instruction otherwise, is to always
produce a confident-sounding answer — that's what most of its training
rewards. Left to its own judgment, weak or irrelevant retrieved context
is more likely to produce a hallucinated (confidently made-up) answer than
an honest refusal. A direct instruction in the system prompt closes that
gap without needing any extra code to detect "did retrieval actually find
anything relevant" — the model handles that judgment call itself, guided
by an explicit rule.

## Consequences
- No additional relevance-checking logic is needed in `retrieval_service.py`
  itself; the guard lives entirely in the prompt.
- This depends on the model reliably following instructions — if we later
  see it still guessing despite the instruction, we'd need to add an
  explicit relevance threshold on the retrieved chunks' distance scores.

## Scale, cost, and on-call reality
The real risk isn't cost, it's silence. LLMs don't follow instructions
with 100% reliability — some non-zero fraction of the time, the model will
still produce a confident-sounding wrong answer despite the instruction,
and nothing in this codebase currently measures that rate. There's no
automated evaluation harness yet (build-order step 9) to catch a
hallucinated answer before a user sees it; today, the only backstop is a
human noticing an answer looks wrong. That's an honest gap, not a solved
problem — this ADR reduces hallucination risk, it doesn't eliminate it.

Cost-wise this is free — it's a fixed string added to a prompt we're
already sending, no extra API call, no added latency. Compare that to the
deferred alternative (a code-level cosine-distance relevance threshold),
which would need real tuning against labeled data before being
trustworthy, and would need active monitoring afterward — set the
threshold too aggressively and the system starts saying "I don't know" to
questions it could have actually answered, which is its own quiet failure
mode nobody would notice without dashboards tracking refusal rate.
