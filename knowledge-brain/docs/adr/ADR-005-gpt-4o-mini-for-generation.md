# ADR-005: Use gpt-4o-mini for answer generation, not gpt-4o

## Status
Accepted

## Context
The generation step needs an LLM to write an answer from retrieved
chunks. OpenAI offers models at different capability and cost points;
this project already uses OpenAI for embeddings, so an OpenAI chat model
was the natural default provider to start with.

## Options considered
1. **gpt-4o-mini** — cheaper and faster, less capable at complex,
   open-ended reasoning.
2. **gpt-4o** — more capable, roughly 15x more expensive per request.

## Decision
Start with gpt-4o-mini (Option 1).

## Reasoning
This task — answering a question using only a small set of retrieved
chunks handed directly to the model — is "grounded" question answering,
not open-ended reasoning. It doesn't require the model to draw on broad
world knowledge or perform multi-step reasoning, which is where gpt-4o's
extra capability matters most. Given that, the extra cost of gpt-4o isn't
justified yet, especially while the project is still in development and
being tested repeatedly.

## Consequences
- If answer quality on harder questions later becomes a real, observed
  problem (not just a guess), this is a one-line config change
  (`GENERATION_MODEL` in `.env`) to upgrade to gpt-4o — no code changes
  needed, since the model name is already externalized as a setting.

## Scale, cost, and on-call reality
The gap between these two models is roughly 15-20x in per-token price,
which turns into a real budget line, not a rounding error, once query
volume is non-trivial. At 10,000 queries a month, with roughly 1,500 input
tokens (retrieved chunks plus the question) and 300 output tokens each,
the dollar difference between the two models is the gap between "a few
dollars" and "tens of dollars" a month for this workload alone — small at
today's scale, but the dashboard this project's planned frontend
explicitly tracks "cost per query" for exactly this reason: it compounds
directly with usage, unlike most infrastructure costs which step up in
chunks.

This decision is also cheap to reverse under pressure — no redeploy, no
code change, just an environment variable — which matters operationally:
if answer quality becomes a live incident (users reporting bad answers),
the mitigation is a config change and restart, not a code review and
release cycle. That reversibility was part of why starting with the
cheaper model was low-risk in the first place.
