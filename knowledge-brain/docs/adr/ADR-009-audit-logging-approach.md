# ADR-009: Audit logging placement and insert-only enforcement

## Status
Accepted

## Context
The project needs an append-only audit trail of state-changing user
actions (document uploads, queries made). Two separate decisions were
needed: where in the code the logging call should happen, and how to
actually enforce that the log can only ever be added to, never edited or
deleted.

## Decision 1: Log from the route layer, not the service layer

### Options considered
1. **Route layer** — call `AuditRepository.log_action(...)` directly
   inside `documents.py`/`query.py`, after the underlying service call
   succeeds.
2. **Service layer** — have `IngestionService`/`RetrievalService` call the
   audit repository themselves as part of their own logic.

### Decision
Route layer (Option 1).

### Reasoning
Audit logging is about recording that "a request to do X happened,"
which is inherently a concern of the API boundary, not the business
logic itself. Routes already have direct access to `get_correlation_id()`
and to the raw request data (filename, question text) without needing it
threaded further down. Keeping it in routes also means services stay
focused purely on their actual job — extracting/chunking/embedding, or
retrieving/generating — with no awareness that "being audited" is even a
concept, matching the same separation-of-concerns reasoning behind
keeping repositories and services apart.

## Decision 2: Enforce insert-only at the code level, defer database-level enforcement

### Options considered
1. **Code-level only** — `AuditRepository` simply has no update or delete
   methods; nothing in the codebase can modify a row after it's written.
2. **Database-level** — revoke `UPDATE`/`DELETE` grants on the
   `audit_log` table for the application's database role, so even a
   direct SQL connection couldn't alter it.

### Decision
Code-level now (Option 1); database-level deferred.

### Reasoning
True database-level enforcement requires a database role that isn't a
superuser — superusers bypass all permission restrictions, including
`REVOKE`. Our local `knowledge_brain` role currently is a superuser, so
setting up real enforcement means introducing a second, deliberately
restricted role and changing how the app connects — a real infrastructure
change, not a code change, and one that should be run by hand per the
project's "you run infra commands yourself" rule rather than folded
silently into this feature. Code-level enforcement is honest about this
limitation rather than pretending to guarantee something it doesn't yet.

## Consequences
- Anyone extending `IngestionService`/`RetrievalService` directly (bypassing
  the route) would skip audit logging entirely — acceptable for now since
  the API routes are the only entry points, but worth remembering if a
  second entry point (e.g. a CLI or worker) is ever added.
- The audit log is not yet tamper-proof against a direct database
  connection or a bug elsewhere in the codebase that imports `AuditLog`
  directly and calls `session.delete(...)` on it — closing this gap
  requires the database role work described above.

## Scale, cost, and on-call reality
Two gaps worth naming precisely, not just "it's not perfect yet." First,
the real enterprise fix for tamper-proofing isn't just revoking
`UPDATE`/`DELETE` grants on a non-superuser role — production audit logs
are commonly shipped to genuinely separate, write-once storage (e.g. Azure
Blob Storage with an immutability policy, or a dedicated audit service),
specifically because "a table in the same database as everything else,
reachable by any role with enough privilege" isn't a real compliance
boundary even with grants revoked. That's the actual target, not a
restricted Postgres role as an end state.

Second, this table has no retention or archival policy today. Every
query and every upload writes a row, unindexed beyond its primary key, with
no partitioning. At meaningful query volume this table grows unbounded —
not a performance problem yet at this project's scale, but a known,
un-actioned gap rather than something quietly assumed to be fine forever.
Cost-wise, storage for audit rows is cheap in isolation, but an
unbounded, unpartitioned table is the kind of thing that turns into a
surprise migration project later if left unaddressed.
