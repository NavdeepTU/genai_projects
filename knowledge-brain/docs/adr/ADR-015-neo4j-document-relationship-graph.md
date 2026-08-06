# ADR-015: Neo4j document relationship graph, built from extracted references

## Status
Accepted

## Context
Everything built so far finds chunks that read *similarly* to a
question — vector search on meaning, keyword search on exact terms.
Neither can answer a structurally different kind of question: "what
does this document explicitly reference," regardless of how similarly
worded the two documents are. `CLAUDE.md` names Neo4j for exactly this
(build-order item 6), but never specifies *which* kind of relationship
to track — that was the first real decision this feature needed.

## Options considered
1. **Topic clusters an LLM infers** — link documents an LLM judges to
   be "about the same thing."
2. **Explicit references extracted from content** — link documents
   based on specific, named things one document mentions (error codes,
   ticket numbers, policy names) that another document actually
   contains.
3. **Shared authorship/ownership metadata** — link documents written by
   the same person or team.

## Decision
Option 2 — explicit references extracted from a document's own text.

## Reasoning
Option 1 was rejected because it substantially duplicates a capability
that already exists: "these two documents are about the same topic" is
close to exactly what an embedding comparison already measures.
Building a second, more expensive system (an LLM call per document,
written into a whole separate database) to answer a question vector
search can already answer on the fly would be unjustified complexity —
the same reasoning that kept this project on pgvector instead of
standing up Qdrant early (ADR-002): don't add a new stateful system
unless it does something the existing one genuinely can't.

Option 3 was rejected for now, but for a different, practical reason:
it's not actually buildable today. The `Document` model has no
author/owner field, and no upload flow captures that metadata — adding
it would mean a separate change to ingestion before a relationship
graph could even use it. Worth revisiting once there's a real reason to
capture that metadata, not before.

Option 2 was chosen because it's the one thing vector/keyword search
structurally *cannot* do: two documents can use completely different
wording (low embedding similarity) while one still needs to explicitly
point at the other — a policy and its replacement, a support ticket and
the specific KB article it names. That's a real, distinct capability,
not a re-implementation of something that already exists.

## Consequences
- New infrastructure: Neo4j running in Docker (`docker-compose.yml`),
  its own driver/session setup (`app/core/graph_database.py`), and a
  dedicated repository (`app/repositories/graph_repository.py`) — the
  only place that writes Cypher, mirroring `DocumentRepository`'s role
  for Postgres.
- Two new circuit breakers: `neo4j` (all graph reads/writes) and
  `openai_reference_extraction` (the LLM call that finds mentions) —
  both independent of the three that already existed, consistent with
  ADR-010's one-per-external-dependency rule. This project now depends
  on *five* independent external call sites for a single query-with-graph-context
  request to fully succeed.
- **One-hop traversal only, by deliberate scope decision** — the query
  pipeline asks "what does this document directly reference," never
  "what does that reference, in turn." Unbounded traversal would mean
  unbounded extra context and unbounded cost per query; one hop is a
  small, known, capped addition (see below for a concrete number).
- **The graph is best-effort, same as reranking (ADR-013), not
  load-bearing like OpenAI's embedding/generation calls.** Neo4j being
  unreachable degrades to "no extra context," not a failed upload or a
  failed query — verified live for both the read path (`_graph_context_node`
  skips gracefully) and, implicitly, the write path (only `CircuitOpenError`
  is caught around reference-building, so an upload still succeeds
  without graph links if Neo4j is down).
- `MERGE`, not `CREATE`, for every node and edge written — makes
  re-processing the same document idempotent instead of accumulating
  duplicate nodes.
- Self-references are explicitly filtered out when resolving a mention
  (`build_references` skips any match belonging to the same document
  being processed) — without this, most edges would be documents
  pointing at themselves, since a document's own text usually contains
  whatever it mentions.
- The snippet pulled from each referenced document is deliberately
  naive: just that document's *first* chunk, not the chunk most
  relevant to the current question. A more accurate version would
  re-run retrieval against the referenced document specifically — not
  built here, a known simplification, not an oversight.
- Verified live end-to-end, not just read: two real documents were
  ingested, one mentioning a ticket ID the other actually defines;
  `build_references` correctly resolved the mention via the existing
  `find_by_keyword` (no new search logic needed) and wrote the edge;
  and a question answerable only by combining *both* documents came
  back correct, citing the detail that existed solely in the
  graph-referenced document.

## Scale, cost, and on-call reality
Reference extraction adds one more LLM call per document upload — at
this project's document sizes, a small, fixed cost, comparable to the
generation call already made per query. The real scale concern isn't
cost, it's **write volume during ingestion**: every mention gets its
own `find_by_keyword` call, so a document with many distinct mentions
means many extra Postgres queries synchronously, during the same
upload request that's already running the full ingestion pipeline
(ADR-001's existing connection-pool-hold concern gets worse, not
better, with this feature added on top).

On the read side, a query that finds graph context now makes one Neo4j
lookup per *unique* source document among the reranked chunks — bounded
by `retrieval_top_k` (5), so at most 5 extra graph lookups, not one per
chunk. Combined with the LangGraph retry loop from ADR-014, a single
query's worst-case external call count keeps growing: embedding, two
searches, reranking, possibly a rewrite-and-retry round, and now up to
5 graph lookups plus their Postgres snippet fetches. None of this is
metered or visible on a dashboard yet — same on-call gap already named
in ADR-014, now with one more contributor to it.

`MATCH (d:Document {id: $document_id})` currently runs without an index
— fine at dozens of documents, a full label scan at real scale. The fix
is a Neo4j range index on `Document.id`, the same category of
deliberately-deferred index work already tracked for pgvector (HNSW)
and full-text search (GIN) — not urgent now, but the same shape of gap,
worth remembering alongside those two rather than as a new, separate
concern.
