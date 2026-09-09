# ADR-048: PII human review workflow

## Status
Accepted.

## Context
Since ADR-018, a document flagged for PII stops at `PENDING_REVIEW` and goes
no further — never chunked, never embedded, never searchable. That was the
right call for the automated check itself, but it was also a dead end:
nothing in this system ever let anyone act on a held document. An admin
had no queue to look at, an uploader had no way to say "I've looked at
this, it's fine," and a document could sit flagged forever with no path to
either joining the knowledge base or being formally rejected.

The request was specific: a flagged document should not go straight to an
admin. It should be visible to the person who uploaded it, with a button
to submit it for review. Only after that submission should an admin see
it, and only an admin can approve or reject it. Approval makes the
document available; rejection is final — no second review can be
requested.

## Options considered

**Who can review a submitted document:**
1. **Any admin within the document's own tenant** — the chosen approach.
2. Any admin in the system, full stop, matching the literal wording of "it
   can be any admin." Rejected outright: this system is multi-tenant
   (ADR-046), and letting an admin from a different company review another
   company's flagged PII content would be exactly the cross-tenant leak
   ADR-046 spent a whole session closing elsewhere. The request's wording
   was read in context, not literally, and confirmed before building
   anything.

**What "approved" actually does to the document's content:**
1. **Re-run the full ingestion pipeline on the original text — chunk it,
   embed it, make it searchable — PII included** — the chosen approach.
   An admin's approval is a deliberate, one-time, audited override of this
   project's own Requirement 4 ("never embed raw PII"), not a blanket
   policy change: it applies to the one document a specific admin
   explicitly signed off on, nothing else.
2. Redact the detected PII before embedding. Rejected: this project has no
   redaction capability at all, and building one — deciding what "safe to
   embed" text even looks like after removing names and numbers from the
   middle of sentences — is a different, much larger feature than what was
   asked for.
3. Only unlock *viewing* the file, never make it searchable. Rejected:
   "then only that document is available within that tenant" reads as
   becoming a normal, searchable document — a document that can never be
   found by a question isn't meaningfully "available" in this system.

**What happens to a rejected document's data:**
1. **Leave the row and file exactly where they are, permanently inert** —
   the chosen approach, matching this project's append-only audit
   philosophy elsewhere. An uploader who wants it gone can still use the
   existing delete flow (ADR-045) themselves.
2. Auto-delete the file and/or row on rejection. Rejected: silently
   destroying data as a side effect of a status change is a bigger,
   separate decision than "reviewed and declined," and would remove the
   uploader's own ability to see what happened to their upload.

## Decision
Three new states extend the existing PII-hold mechanism:
`PENDING_REVIEW` (unchanged meaning — flagged, held, not yet submitted) →
`IN_REVIEW` (submitted, in the admin queue) → `READY` (approved) or
`REJECTED` (terminal). A new, nullable `Document.uploaded_by` column
reintroduces per-document uploader tracking — deliberately removed
entirely by ADR-046 — scoped specifically to this workflow: a document in
any of the three review-adjacent states is visible only to its own
uploader and to admins of that same tenant, the first and only exception
to "tenant membership is the whole of document access control." Once
approved, a document drops that restriction and becomes normal,
tenant-wide visible, exactly like any other document. `IngestionService.approve_and_process`
re-downloads the original file from Blob Storage (saved before the PII
check ever ran, per ADR-044, and never discarded) and re-enters the
pipeline at extraction, skipping the PII gate entirely — the human
decision replaces it, it doesn't repeat it.

## Reasoning
Reading "any admin" as "any admin in this document's own tenant" rather
than literally was a deliberate correction, not a guess — multi-tenancy's
entire premise (ADR-046) is that one tenant's data, especially PII, never
crosses into another's view. A feature request's literal wording doesn't
override a system's own established security boundary; where the two
conflicted, the boundary won, and the interpretation was confirmed with
the person who asked before any code was written, not decided unilaterally
after the fact.

Making approval a real, full override — embedding the original PII-bearing
text — was chosen because a human-in-the-loop exception to an automated
compliance rule is a legitimate, common enterprise pattern, and because
the alternative (redaction) is a materially different, larger feature that
was never actually requested. The cost of this choice is worth stating
plainly: this system can now knowingly embed PII into its vector index, on
a document-by-document basis, whenever an admin decides to. That is by
design, not an oversight — the audit log records exactly who made that
call and when, which is what makes it a supervised exception rather than a
silent policy change.

## Consequences
- `app/models/document.py`: `DocumentStatus` gains `IN_REVIEW`, `REJECTED`;
  `Document` gains a nullable `uploaded_by` foreign key to `users.id`.
- `app/repositories/document_repository.py`: `create_document` takes
  `uploaded_by`; `list_documents_for_tenant` gains its first-ever
  non-tenant visibility filter; new `submit_for_review`, `reject_document`,
  `list_review_queue_for_tenant` (itself tenant-scoped).
- `app/services/ingestion_service.py`: new `approve_and_process`, and the
  chunk/embed/save tail shared with `process_document` was factored into
  `_chunk_embed_and_save` so the two entry points can't drift apart.
- `app/api/documents.py`: new `_visible_to_caller` helper (uploader-or-admin
  check), applied to status, content, and delete routes; new
  `POST /{id}/submit-review`.
- `app/api/admin.py`: new `GET /review-queue`, `POST /documents/{id}/approve`
  (schedules `approve_and_process` as a background task, same
  return-immediately shape every other document-processing step already
  uses), `POST /documents/{id}/reject`.
- `app/core/admin_auth.py`: `is_admin_user` factored out of `require_admin`
  so admin-ness can be one branch of a broader visibility check, not only
  a hard gate.
- Frontend: a "Send for review" button and `in_review`/`rejected` states on
  the document card; a new Admin page "Review queue" section with
  Approve/Reject actions.
- A real migration bug, caught by the very first live signup after
  running it: the hand-run SQL used the lowercase enum *values*
  (`'in_review'`, `'rejected'`) instead of the uppercase *names*
  (`'IN_REVIEW'`, `'REJECTED'`) every other `DocumentStatus` value in this
  database has actually been stored as since the very first migration —
  invisible until the first query ever compared against more than one
  status value in a list. Fixed with `ALTER TYPE ... RENAME VALUE`, safe
  since nothing had used either value yet.
- Tests: 150 → 170 passing (20 new): repository-level visibility and
  transition tests, `approve_and_process`'s reprocessing and failure
  paths, route-level tests for submit/approve/reject including the
  cross-tenant admin-scoping check, and frontend tests for every new
  document-card state and the review-queue UI.
- Verified live end to end, not just by test: a real flagged document,
  visible only to its uploader; submitted, approved, and confirmed
  actually re-embedded (its real PII-bearing text present in `chunks`) and
  instantly visible tenant-wide; a second document rejected and confirmed
  terminal — zero chunks, no resubmission option, visible only to its
  uploader with a plain "rejected" state.

## Scale, cost, and on-call reality
No new external dependency. Approval's cost is exactly a second, full
ingestion pass — the same extraction, chunking, and embedding cost a
normal upload already pays, paid again only for documents an admin
explicitly approves, not automatically. The real, permanent trade-off
worth naming: this workflow gives a tenant's admins a supervised, audited
way to override this project's own PII-detection safeguard, document by
document. That is the feature working as designed, not a gap — but it
means "no raw PII in the vector database" is no longer an absolute
guarantee this system enforces on its own; it is a default that a
specific, logged human decision can knowingly set aside.
