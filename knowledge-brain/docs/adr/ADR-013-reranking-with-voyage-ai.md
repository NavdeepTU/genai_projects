# ADR-013: Use Voyage AI's hosted Rerank API for reranking

## Status
Accepted

## Context
Hybrid search (ADR-011) merges vector and keyword search results with
Reciprocal Rank Fusion, but both underlying searches are approximate —
they compare the question and each chunk as *separately*-computed
representations (an embedding, or a `tsvector` match), never directly
comparing the actual question text against a specific chunk's actual
text. Reranking adds a second pass over hybrid search's candidate
results: a method that looks at the question and each candidate chunk
*together*, to reorder and narrow them down before generation.

## Options considered
1. **A local, open-source cross-encoder** (e.g. via `sentence-transformers`/
   Hugging Face) — runs on the same machine, no per-call cost, but a heavy
   new dependency (PyTorch, downloaded model weights). This project has
   had zero local model inference so far; every AI capability so far goes
   through a hosted API.
2. **Voyage AI's hosted Rerank API** — a dedicated, purpose-built
   reranking vendor. A new vendor relationship (its own API key,
   settings, circuit breaker), but purpose-trained for exactly this task.
3. **Prompt-based reranking via OpenAI**, already integrated — reuse the
   existing client, settings pattern, and circuit-breaker approach
   already used for embedding and generation. No new vendor or
   dependency, but not a model actually trained to score relevance.

## Decision
Voyage AI's hosted Rerank API (Option 2).

## Reasoning
Option 3 would have been the easiest to wire in — same client, same
settings shape, same circuit-breaker pattern already proven twice in this
codebase. It was deliberately not chosen: the goal was specifically to
use a dedicated, purpose-built reranking tool, on the reasoning that a
model actually trained for relevance scoring should give a more
trustworthy signal than repurposing a general-purpose chat model for a
scoring task it wasn't specifically trained for.

Between the two purpose-built options, Voyage was chosen over a local
cross-encoder (Option 1) to avoid pulling a heavy new local ML dependency
into a project where every AI capability so far has gone through a
hosted API, not local inference. Voyage's free tier — 200 million tokens
per account, confirmed by checking current pricing directly rather than
assuming — also made cost a non-factor at this project's scale, unlike
Cohere's alternative trial (1,000 calls/month, explicitly not for
production use), which was considered and rejected for that reason.

## Consequences
- New settings: `voyage_api_key`, `reranking_model` (`rerank-2.5-lite`),
  `retrieval_candidate_pool` (20). `retrieval_top_k` is unchanged in
  meaning (5) but now decided *after* reranking, instead of directly by
  the two searches.
- Both searches, and RRF's own merge, now operate over the wider
  candidate pool (20) instead of `retrieval_top_k` — this also resolves a
  previously-deferred code-review finding: RRF used to be capped at
  `retrieval_top_k` before merging, so it could never reward a chunk both
  searches ranked just outside that cutoff. Widening the pool for
  reranking's sake fixes that as a side effect, not a separate task.
- Reranking gets its own independent circuit breaker (`voyage_reranking`),
  consistent with ADR-010's one-breaker-per-external-dependency rule — a
  Voyage outage can't trip the OpenAI circuits, or vice versa.
- If Voyage's circuit is open, the system degrades to hybrid search's own
  RRF order rather than failing the request — same philosophy as
  ADR-012's search-failure fallback. Verified for real, not just read:
  forcing `CircuitOpenError` still produced a correct answer, using RRF's
  own top slice instead of Voyage's reordering.
- Adding `voyageai` as a dependency pulled in a much heavier package tree
  than expected — `numpy`, `pillow`, `tokenizers`, `huggingface-hub`,
  `langchain-core`, 32 packages total. A real, if modest, cost of choosing
  a vendor SDK over a plain HTTP call, worth remembering even though the
  vendor itself is a hosted API, not a local model.
- A real secret-handling mistake happened while setting this up: the
  Voyage API key was briefly pasted into the tracked `.env.example`
  instead of the git-ignored `.env`. Caught before anything was
  committed (confirmed via `git log`/`git status`), fixed immediately, and
  the exposed key was rotated anyway since it had already appeared in
  conversation history — cheap insurance for something free to redo.

## Scale, cost, and on-call reality
At this project's scale, cost is effectively zero. A typical reranking
call sends the question plus 20 candidate chunks — even generously
estimated at ~650 tokens per chunk, that's roughly 13,000 tokens per
query, meaning the 200-million-token free tier covers well over 15,000
queries before any real billing starts. Paid pricing after that (`$0.02`
per million tokens for the lite model) stays cheap even at real usage.

The ownership picture is more interesting than the cost picture. This
system now depends on *three* independent external AI vendor
relationships for one query to fully succeed — two OpenAI call sites
(embedding, generation) plus Voyage — three circuit breakers to reason
about independently, three sets of credentials to rotate, three vendors
whose outage surfaces differently. Worth naming an asymmetry here
honestly: reranking is the *only* one of the three that's genuinely
optional today. If OpenAI's embedding or generation circuit opens, the
request still fails (cleanly, as a `503`, but it fails) — there is no
fallback that lets a query succeed without an embedding or without a
generated answer. Voyage is different: its failure degrades the
*quality* of retrieval, not the ability to answer at all. That's a
meaningful, precise distinction between "load-bearing dependency" and
"best-effort enhancement," and it's the kind of thing worth being able to
say plainly in an interview rather than treating all three vendors as
equivalent risk.
