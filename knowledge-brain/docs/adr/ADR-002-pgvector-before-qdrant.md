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
