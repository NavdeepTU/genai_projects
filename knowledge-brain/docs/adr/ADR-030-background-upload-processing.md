# ADR-030: Background document processing with per-stage progress tracking

## Status
Accepted. Extends ADR-001, which already named this as the intended next
step once synchronous processing became a real problem, not just a
theoretical one.

## Context
The upload endpoint has processed documents fully synchronously since
ADR-001: the HTTP request itself ran extraction, PII detection,
chunking, embedding, and saving, and only returned once the document
reached `READY` or `FAILED`. ADR-001 accepted that trade-off
deliberately, but named the exact condition under which it should
change — a large document making a user wait 30+ seconds for a
response — and named the exact fix: "changing the upload endpoint to
return immediately... deferring the rest of the pipeline."

With the frontend's Document Library page now built (ADR-029), that
condition became concrete rather than theoretical: a real user watching
a real upload button freeze for the duration of a PDF's embedding calls
is a materially worse experience than an API client waiting on a
synchronous response. This session builds the fix ADR-001 already
called for, plus the frontend to make it visible.

## Options considered
For how to run the pipeline after the response is sent:
1. **FastAPI `BackgroundTasks`** — schedule the pipeline as a function
   that runs after the response goes out, still inside the same web
   server process.
2. **Kafka (Azure Event Hubs)** — publish an event, let a separate
   worker process consume it and run the pipeline.

For how to track progress:
1. **Reuse `DocumentStatus`** — add finer-grained values like
   `extracting`, `chunking`, `embedding` directly to the existing
   status enum.
2. **A second, purpose-built `processing_stage` column** — a new enum
   used only for progress display, kept separate from `status`.

For what the upload response should return:
1. **Return `document.status` as-is** (`pending`) from the fast,
   synchronous half of the work, before the background task starts.
2. **Force it to `processing` in the response**, even though the
   database write to `processing` happens moments later, inside the
   background task itself.

## Decision
`BackgroundTasks`, not Kafka. A new `ProcessingStage` enum and
`processing_stage` column, kept fully separate from `DocumentStatus`.
The upload response returns the document's real, current `status`
value at response time (`pending`) rather than a value we haven't
actually written to the database yet.

## Reasoning
Kafka was rejected for the same reason ADR-001 rejected it originally:
it solves connection-pool exhaustion under sustained concurrent load,
and nothing this session measured or observed suggests that load exists
yet. Reaching for a message broker and a separate worker process before
that problem is real would be solving an imagined scale problem instead
of the actual one in front of us — a slow, blocking UI on a single
upload. `BackgroundTasks` fixes exactly that, with no new process, no
broker, and no new operational surface to own. This ADR extends ADR-001
rather than reversing it; the Kafka trigger condition ADR-001 named
hasn't happened, so the reasoning for deferring it still holds.

Reusing `DocumentStatus` for stage tracking was rejected because status
is a load-bearing field — permission checks, the document list page,
and business rules like "only a `READY` document is a valid citation
source" all depend on it staying a small, stable set of terminal-ish
states. Adding six more transient values to that same enum would mean
every piece of code that currently switches on `DocumentStatus` now has
to account for values it never actually needs to react to. A second
column, meaningful only while `status == PROCESSING` and ignored by the
frontend the moment a terminal status is reached, keeps that separation
clean: nothing outside the progress bar has to know `ProcessingStage`
exists.

Returning the real `pending` status, not a forced `processing`, was the
one adjustment made after the first pass at this feature: `status`
becoming `PROCESSING` is itself a database write that happens inside
the background task, which by definition hasn't run yet at the moment
the response is being built. Claiming `processing` in the response
would be describing a write that hadn't happened — the response has to
describe the state as it actually is, not the state we expect a moment
later. The frontend's first poll, seconds later, is what actually shows
`processing`.

## Consequences
- `IngestionService.ingest_document` split into two methods:
  `create_document` (create the row, grant access — fast, synchronous,
  runs before the response) and `process_document` (the full pipeline —
  runs in the background, takes a `document_id` rather than a
  `Document` object, since the caller by then only has an id, not the
  ORM-tracked object from the original request's session).
- The background task opens its own fresh database session
  (`AsyncSessionLocal`) and its own fresh Neo4j session, rather than
  reusing the request's — both are already torn down by the time a
  background task actually executes, since they're scoped to the
  request/response cycle, not to the task queued on top of it.
- `correlation_id` is captured in the endpoint and passed into the
  background task as a plain argument, not read via
  `get_correlation_id()` from inside it — that function reads a
  contextvar the middleware resets back to empty the moment the
  response leaves the endpoint, before the background task runs; a log
  line written from inside the task that called it directly would
  silently log a blank ID.
- New `DocumentRepository` methods: `update_processing_stage` (mirrors
  `update_status`'s shape exactly), `get_document_for_user`
  (permission-checked single-document lookup, same
  `DocumentPermission` join `list_documents_for_user` already uses),
  and `get_by_id` (no permission check, for the background task's own
  internal use deciding whether to build graph references — mirrors
  the existing `find_by_keyword_unrestricted`).
- New `GET /documents/{document_id}/status` endpoint returns 404
  identically whether the document doesn't exist or the caller simply
  lacks access to it — the two cases are deliberately indistinguishable
  from outside, so a user can't use this endpoint to fingerprint the
  existence of documents they were never granted access to.
- Frontend: two new Next.js Route Handlers
  (`app/api/documents/upload/route.ts`,
  `app/api/documents/[id]/status/route.ts`) proxy both calls
  server-to-server, so `BACKEND_GATEWAY_SECRET` never reaches
  client-side JavaScript and no CORS configuration is needed — the
  browser only ever calls same-origin Next.js paths. A new
  `UploadDropzone` client component handles drag-and-drop, uploads via
  the proxy, then polls the status proxy every 2 seconds, rendering a
  per-stage progress bar until the document reaches a terminal status,
  at which point it triggers a `router.refresh()` of the document list
  and removes itself.
- Verified live: uploaded a real file through both the raw backend and
  the frontend proxy, watched `processing_stage` move through its real
  values via direct polling, confirmed a no-access user gets 404 on the
  status endpoint, confirmed a rejected file extension returns 400, and
  watched the drag-and-drop flow complete in an actual browser in both
  light and dark mode.

## Scale, cost, and on-call reality
`BackgroundTasks` runs inside the same server process and the same
worker as the request that scheduled it — it is not a separate
process, has no independent health signal, and shares CPU with every
other request that process is currently handling. A CPU-heavy step in
the pipeline (there currently isn't one — extraction, chunking, and the
embedding/PII calls are all I/O-bound, waiting on external services, not
computing locally) would visibly slow down unrelated requests on the
same worker. If Uvicorn is ever run with multiple worker processes, a
background task scheduled on worker A has no relationship to workers
B/C — this is fine today since nothing cross-worker depends on it, but
it's the concrete reason a true queue would eventually be needed at
scale: `BackgroundTasks` has no shared state across processes, no
retry, and no persistence — a server restart or crash mid-task silently
drops it, leaving a document stuck at whatever `processing_stage` it
last reached, with `status` never reaching a terminal value. That
failure mode doesn't exist for a Kafka-backed worker, where an
unacknowledged message gets redelivered. This is the same number ADR-001
already named as the real trigger for moving to Kafka: sustained
concurrent uploads high enough to matter, now with a second, related
failure mode — worker crashes silently orphaning in-flight background
tasks — worth naming explicitly as part of that same future decision,
not a new one.
