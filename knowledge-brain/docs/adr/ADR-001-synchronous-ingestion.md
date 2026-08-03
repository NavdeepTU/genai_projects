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
