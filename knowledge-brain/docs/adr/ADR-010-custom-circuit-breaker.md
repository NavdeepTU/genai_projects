# ADR-010: Build a custom circuit breaker; catch it explicitly only where a graceful response is possible

## Status
Accepted

## Context
The two OpenAI call sites (`embedding.py`, `generation.py`) needed
protection against repeated failures — instead of every request
separately waiting for a doomed call to time out, a circuit breaker
should fail fast once a failure pattern is detected.

## Decision 1: Build a custom `CircuitBreaker`, not a library

### Options considered
1. **Custom implementation** — a small `CircuitBreaker` class built from
   scratch (`app/core/circuit_breaker.py`).
2. **An existing library** — e.g. `pybreaker` or `circuitbreaker`.

### Decision
Custom implementation (Option 1).

### Reasoning
Two reasons, not just one: it avoids adding a new dependency for
something genuinely simple to implement correctly (a handful of states
and a rolling time window), and it's consistent with how the rest of
this project was built — extraction, chunking, and the embedding/generation
calls were all written by hand rather than reached for off-the-shelf, so
the mechanism is fully understood rather than a black box. A circuit
breaker is small enough that building it doesn't cost much, and the
payoff is actually being able to explain exactly how it works, not just
that it works.

## Decision 2: Handle the fallback differently per call site

### Options considered
1. **Handle uniformly** — catch `CircuitOpenError` explicitly in both
   `documents.py` and `query.py`, with custom handling in each.
2. **Handle only where it changes the outcome** — let `CircuitOpenError`
   propagate naturally in ingestion (where it's already caught by
   `IngestionService`'s existing failure handling), and only add explicit
   handling in `query.py`, where there's no existing catch-all and the
   user would otherwise see a raw 500.

### Decision
Option 2.

### Reasoning
`IngestionService.ingest_document` already wraps its whole pipeline in a
`try/except Exception` that marks the document `failed` — since
`CircuitOpenError` is an `Exception`, it's already handled correctly with
zero new code. Adding an explicit catch there too would be duplicate
logic with no behavioral difference. `query.py` has no equivalent
catch-all, so without explicit handling, an open circuit there would
surface as a generic, unhelpful 500 error instead of a clear "temporarily
unavailable" message.

## Consequences
- Two independent `CircuitBreaker` instances exist (`openai_embeddings`,
  `openai_generation`) — a run of embedding failures doesn't affect
  generation's circuit, and vice versa.
- `query.py` returns a `503` with a clear message when its circuit is
  open, and skips writing an audit log entry for that request, since no
  query was actually answered.
- The circuit breaker's state lives in memory, per process — restarting
  the server resets it, and running multiple server instances means each
  has its own independent circuit state rather than a shared one. Worth
  revisiting once this runs as more than a single local process.

## Scale, cost, and on-call reality
The per-process state limitation isn't just a performance footnote — it
produces a genuinely confusing on-call signal at real scale. On a
multi-replica deployment, one instance could see 3 failures and open its
circuit while three other replicas, having not personally observed those
failures, keep calling OpenAI successfully. Dashboards would then show
inconsistent, partial error rates split oddly across replicas rather than
a clean "OpenAI is down" signal — which reads as a bug in the circuit
breaker itself, not protection working correctly. That's arguably worse
than having no circuit breaker at that scale, because it actively misleads
whoever's debugging it. The real fix is moving the failure count into
shared state (Redis, given this project's planned stack) so all replicas
agree on the circuit's state.

The specific numbers chosen — `failure_threshold=3`, `window_seconds=60`,
`recovery_timeout=60` — were picked for a low-traffic dev environment,
where waiting for many failures before protecting means many of this
project's few real requests hit a doomed call firsthand. At production
request volume, 3 failures in 60 seconds could trip on ordinary noise —
three unlucky timeouts inside a burst of thousands of requests, not a real
outage — so these thresholds would need retuning against real traffic
statistics, not carried over as-is. Cost is negligible either way; this is
in-process logic, not new infrastructure.
