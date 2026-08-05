# ADR-001: Process document ingestion synchronously, not with a queue

## Status
Accepted

## Context
When a user uploads a document, it needs to be extracted, chunked, embedded,
and saved before it's usable. This can be done either synchronously (the
user's request waits for all of that to finish) or asynchronously, by
handing the work off to a background queue (e.g. Kafka) and letting the
user's request return immediately.

## Options considered
1. **Synchronous processing** — the upload request itself runs the whole
   pipeline and returns only once the document is `ready` or `failed`.
2. **Kafka-based background processing** — the upload request saves the
   file and publishes an event; a separate worker service consumes that
   event and runs the pipeline, updating the document's status when done.

## Decision
Start with synchronous processing (Option 1).

## Reasoning
Synchronous processing is far simpler to build, test, and reason about — no
separate worker process, no message broker to run, and no need to handle
the case where an upload "succeeded" but processing is still happening
somewhere else. Our current test documents process in under a second, so
there's no real pain to solve yet.

Kafka is part of this project's planned tech stack, but we're deliberately
adding it later, once we feel a concrete problem it solves — specifically,
once a large document (e.g. a 50-page PDF) makes a user wait 30+ seconds
for a response. Introducing the queue at that point will be a direct fix
to an observed problem, not a guess at future scale.

## Consequences
- Large documents currently block the HTTP request until fully processed.
- If a pipeline step fails partway through, the document is marked
  `failed` (see the repository's `update_status`) rather than left
  ambiguously `pending` forever — this keeps failure handling correct even
  before a queue exists.
- Moving to Kafka later will require introducing a worker process and
  changing the upload endpoint to return immediately after saving the raw
  file, deferring the rest of the pipeline to that worker.

## Scale, cost, and on-call reality
The concrete failure mode isn't "OpenAI is slow" — it's connection pool
exhaustion. SQLAlchemy's async engine defaults to `pool_size=5,
max_overflow=10`, 15 connections total. A synchronous upload holds its
connection for the *entire* pipeline duration — extraction, chunking, and
the embedding call — not just the final save. At roughly 2-30 seconds per
document depending on size, 16 concurrent uploads is enough to exhaust the
pool; the 16th request doesn't fail cleanly, it queues silently waiting
for a connection, so the visible symptom is rising latency, not a clear
error. That's the actual number that would justify Kafka — not "we have a
lot of documents," but "we regularly see 15+ uploads in flight at once."

Cost-wise, this design is free at idle: no new process, no broker, riding
entirely on the FastAPI server we're already running. Kafka's
alternative means an always-on consumer process burning compute 24/7 even
at zero traffic, plus a broker to keep healthy — a real recurring cost for
capability this project doesn't need yet.

The on-call story also differs in kind, not just degree. A stuck
synchronous request shows up immediately as elevated request latency or a
500 in APM — an obvious, well-understood signal. A queue-based failure
(a stalled consumer, growing backlog) is invisible unless someone is
specifically watching consumer lag — a harder failure mode to notice and
a new monitoring surface this project doesn't currently have to own.
