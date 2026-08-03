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
