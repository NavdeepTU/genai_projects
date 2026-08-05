# ADR-006: Use cosine similarity for chunk retrieval

## Status
Accepted

## Context
Finding relevant chunks means comparing the question's embedding vector
against every stored chunk's embedding vector and ranking by closeness.
pgvector supports three comparison operators: cosine distance, L2
(Euclidean) distance, and inner product.

## Options considered
1. **Cosine similarity/distance** — measures the angle between two
   vectors; ignores their magnitude (length).
2. **L2 (Euclidean) distance** — measures straight-line distance between
   two vectors; magnitude affects the result.
3. **Inner product** — a raw dot product; fastest to compute, but only
   meaningful for comparing relevance when vectors are normalized.

## Decision
Use cosine similarity (Option 1).

## Reasoning
Cosine similarity is the metric OpenAI's own documentation recommends for
comparing their embeddings, and it directly captures "how similar in
meaning" two pieces of text are regardless of how long either one is —
which matches our use case exactly, since chunks and questions are rarely
the same length. It's implemented in `document_repository.py` via
SQLAlchemy's `Chunk.embedding.cosine_distance(...)`.

## Consequences
- At real scale, this comparison needs a proper vector index (pgvector
  supports this) to stay fast; right now it's a full scan over all
  chunks, acceptable only because our dataset is tiny.
- If we ever change embedding providers to one that isn't normalized the
  same way, this choice should be revisited.

## Scale, cost, and on-call reality
This choice also locks in which index type is available later: pgvector's
HNSW and IVFFlat indexes are built per operator class (`vector_cosine_ops`
for cosine, `vector_l2_ops` for L2, and so on), so choosing cosine now
isn't just a scoring decision — it determines which index we'd build at
10M+ rows (see ADR-002's math on what an unindexed scan costs at that
size).

The more dangerous failure mode here isn't a crash, it's silent
degradation. If the embedding provider ever changes to one that isn't
normalized the same way, cosine similarity doesn't error — it just quietly
returns worse rankings. Nothing in this codebase would surface that as a
failure; it would look like "the answers got a bit worse" with no clear
cause, and the only real way to catch it is an evaluation harness
(build-order step 9, not built yet) measuring retrieval quality on a fixed
set of test questions before and after any embedding-model change. Cost
is effectively zero either way — this is a scoring-function choice, not
an infrastructure one — but the operability gap (no automated way to
detect this class of regression today) is real and worth naming rather
than assuming "we'd notice."
