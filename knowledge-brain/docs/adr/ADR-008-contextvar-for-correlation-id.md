# ADR-008: Use a ContextVar to share the correlation ID across a request

## Status
Accepted

## Context
A correlation ID is generated once per incoming request, but needs to be
readable from deep inside the call stack — services and the repository —
so it can eventually be included in log lines from anywhere in the
pipeline, not just the route handler.

## Options considered
1. **`request.state`** — FastAPI's built-in per-request storage,
   attached directly to the `Request` object.
2. **Thread it explicitly as a parameter** — pass the correlation ID (or
   the whole `request` object) into every function call that might need
   it: `IngestionService.ingest_document(..., correlation_id)`,
   `DocumentRepository.create_document(..., correlation_id)`, and so on.
3. **`ContextVar`** — a variable that's automatically isolated per
   concurrent request, readable from anywhere in the code running during
   that request, without being passed as a parameter.

## Decision
Use `ContextVar` (Option 3).

## Reasoning
`request.state` only works for code that actually has a reference to the
`request` object — true for route handlers, not true for
`IngestionService`, `RetrievalService`, or `DocumentRepository`, which
are called several layers deep and never receive `request` as a
parameter (intentionally — that's what keeps business logic decoupled
from the web layer). Explicitly threading the ID through every function
signature (Option 2) would work, but means touching every method in the
call chain just for tracing plumbing, and every future method added to
those classes would need to remember to accept and forward it too.
`ContextVar` gives any code running during a request access to the
correlation ID via `get_correlation_id()`, regardless of how deep it is
in the call stack, with zero changes to existing function signatures.

## Consequences
- `get_correlation_id()` is now the standard way to read the current
  request's correlation ID anywhere in the codebase — repositories and
  services can call it directly without needing it passed in.
- The middleware's `try/finally` around `.set()`/`.reset()` is what makes
  this safe under concurrency — without it, a crashed request could leave
  stale context behind for whatever the same worker handles next.
- If the codebase ever adds background jobs or queue consumers running
  outside an HTTP request (e.g. once Kafka is introduced per ADR-001),
  those code paths will need their own way to set a correlation ID, since
  there's no incoming HTTP request to generate one from.
