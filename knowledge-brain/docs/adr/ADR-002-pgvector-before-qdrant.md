# ADR-002: Store chunk embeddings in Postgres + pgvector, not Qdrant

## Status
Accepted

## Context
Each document chunk needs its text and its embedding vector (a list of
numbers representing its meaning) stored somewhere that can later be
searched by similarity. This project's planned tech stack includes both
pgvector (a Postgres extension) and Qdrant (a dedicated vector database).

## Options considered
1. **Postgres + pgvector** — store chunk text and its embedding vector as
   two columns in the same `chunks` table, alongside normal relational
   data like `document_id` and `chunk_index`.
2. **Qdrant** — store embeddings in a separate, purpose-built vector
   database, with chunk text and metadata either duplicated there or kept
   in Postgres and joined at query time.

## Decision
Start with Postgres + pgvector (Option 1).

## Reasoning
Keeping chunk text and its embedding in the same row, in the same
database, as the document's own metadata means one connection, one query
language, and no synchronization problem between two separate systems.
Saving a document and its chunks can happen as a single all-or-nothing
transaction, which would be harder to guarantee across two databases.

Qdrant is built specifically for large-scale, high-performance vector
search and will outperform pgvector once the number of stored vectors gets
large. We're deliberately not reaching for that yet — the plan is to
introduce Qdrant once pgvector's search performance actually becomes a
bottleneck, not preemptively.

## Consequences
- All ingestion code (the repository, the models) treats embeddings as
  just another column, which kept the early implementation simple.
- Vector search performance will eventually need to be re-evaluated as
  data grows; moving to Qdrant later will mean introducing a second
  datastore and keeping it in sync with Postgres.

## Scale, cost, and on-call reality
At 10 million chunks, each a 1536-dimension `float32` vector, the raw
embedding data alone is roughly 10,000,000 × 1536 × 4 bytes ≈ 61 GB —
before indexes, before the chunk text itself. Without a vector index (see
ADR-006), `cosine_distance` at that size is a full sequential scan of that
61 GB on every single query. That's the concrete point where "pgvector's
performance becomes a bottleneck" stops being vague and becomes a specific,
measurable trigger for adding an HNSW index, and eventually Qdrant.

Ownership-wise, pgvector rides entirely on infrastructure already being
paid for and operated — Azure Database for PostgreSQL Flexible Server
already has monitoring, backups, and an on-call runbook by virtue of
existing for the rest of the app's data. Qdrant would be a second stateful
service: its own health checks, its own backup strategy, its own failure
modes to learn — doubling the surface area of "things that can page
someone" to solve a problem (large-scale vector search latency) that
doesn't exist yet at this project's data volume. That operational cost,
not raw query speed, is the real reason this is deferred rather than
built defensively upfront.

Cost concretely: an additional managed Qdrant instance is an added monthly
line item with no current bottleneck to justify it. Revisit only once
query latency, not developer preference, forces the question.
