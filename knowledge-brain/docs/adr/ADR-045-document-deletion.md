# ADR-045: Deleting a document, completely

## Status
Accepted.

## Context
The Document Library page let a user upload a document and, since
ADR-044, view it — but never remove one. "Delete a document" sounds
like a single operation, but this project now stores something about
every document in three separate places: the database (the document
row, its chunks, its permission grants), Blob Storage (the original
file, since ADR-044), and Neo4j (a graph node and any REFERENCES edges
to or from other documents, since ADR-015). A correct delete has to
visit all three, or it just creates a different kind of stale data than
the one it was meant to clean up.

This also surfaced a real, pre-existing gap in the permission model:
`grant_document_access` has never actually been restricted to the
original uploader — its check is `has_access`, the same one every
accessor passes, and there is no separate "owner" concept anywhere in
the schema. In practice this has never mattered, since no frontend UI
for granting access exists at all, so every document today still has
exactly one person with access to it — but it meant deletion's
authorization rule had to be decided deliberately, not inherited from
an "owner" field that doesn't exist.

## Options considered

**Who can delete a document:**
1. **Anyone with access, matching `has_access` — the same rule
   `grant_document_access` already uses** — the chosen approach.
   Consistent with the one authorization rule this project already has
   for documents; introduces no new concept.
2. Add a real "owner" field, distinguishing the original uploader from
   anyone later granted access, and restrict deletion to the owner
   alone. More correct once multi-user sharing is ever actually used,
   but there is no UI for granting access at all today — building an
   ownership model to protect against a scenario that has never
   happened would be speculative scope, not a real requirement yet.

**How cleanup failures across the three systems should behave:**
1. **Blob Storage and Neo4j cleanup are best-effort; the database
   delete is the one part that must succeed** — the chosen approach,
   the same failure-isolation shape this project already applies to
   every external dependency (reranking, graph context, domain
   classification all degrade rather than cascade into a hard
   failure).
2. Treat all three as equally required, failing the whole deletion if
   any one fails. Simpler to reason about in the abstract, but means a
   brief Blob Storage or Neo4j hiccup — services this project already
   treats as allowed to be flaky elsewhere — would leave a user unable
   to delete a document for reasons that have nothing to do with the
   document itself.

## Decision
Anyone with access to a document can delete it — the same `has_access`
rule already used for viewing, listing, and granting access. Deleting
removes the file from Blob Storage and the node (and every edge
touching it) from Neo4j first, both best-effort, then deletes the
document row — whose chunks and permission grants cascade with it
automatically via a new ORM relationship. A confirmation dialog is
required before anything happens; the deleting user's id is recorded
in the audit log alongside the action.

## Reasoning
Matching the existing `has_access` rule rather than introducing
ownership was chosen because there is nothing in this system today that
distinguishes an uploader from someone granted access afterward — since
sharing has no UI and has never been exercised in practice, every
document has exactly one accessor anyway, making the two options
behaviorally identical today. Building a real ownership model now would
be designing for a multi-user scenario that doesn't exist yet, the same
kind of premature scope this project has consistently avoided
elsewhere (a managed domain taxonomy, LLM-generated conversation
titles). If sharing ever gets a real UI, this is the first place that
decision would need revisiting — named here so it isn't forgotten.

Best-effort cleanup for Blob Storage and Neo4j, with the database as
the one required step, follows directly from where each of those
services already sits in this project: both are already behind their
own circuit breaker, already allowed to degrade gracefully elsewhere.
Making deletion different — requiring all three to succeed — would
mean a working, current document could suddenly become undeletable
because an unrelated service had a bad five minutes, which is a worse
outcome than a rare leftover blob or graph node sitting unused.

## Consequences
- `app/models/document.py`: a new `permissions` relationship
  (`cascade="all, delete-orphan"`), mirroring `chunks` — deleting a
  `Document` now cleans up both automatically through the ORM, with no
  separate repository call needed for either.
- `app/repositories/document_repository.py`: new `delete_document`.
  A real bug was caught by its own cascade test before this ever ran
  live: `AsyncSession.delete()` in SQLAlchemy's async ORM is itself a
  coroutine, unlike the sync session's plain method — the first version
  of this method called it without `await`, which produced no error at
  all, just a silently-never-executed delete and a `RuntimeWarning`
  buried in the test output. Fixed before it shipped.
- `app/repositories/graph_repository.py`: new `delete_document_node`,
  using `DETACH DELETE` so both directions of a `REFERENCES` edge (this
  document pointing out, or another document pointing at it) are
  removed in one query, with no dangling edge left behind either way.
- `app/core/blob_storage.py`: new `delete_document`, treating an
  already-missing blob as success rather than an error — the caller
  wants the file gone, and it already is.
- `app/services/document_deletion_service.py` (new): the orchestrator,
  the same small, single-purpose shape as `DocumentGraphService`.
- `app/api/documents.py`: new `DELETE /documents/{document_id}`,
  permission-checked identically to every other document route, an
  audit log entry recording the deleting `user_id`, `204 No Content` on
  success.
- Frontend: a real confirmation dialog — this project's first use of
  Shadcn's `AlertDialog` (added via the CLI, on the already-installed
  Base UI foundation ADR-028 established) — a delete icon-button on
  each `DocumentCard`, a `deleteDocument` client call, and a matching
  Next.js proxy route.
- A real, user-reported layout bug was found and fixed the same
  session, unrelated to the delete logic itself but only clearly
  visible once the delete button gave the header row a second
  fixed-width element to protect: `CardHeader` is a CSS Grid container,
  and — the same footgun flex items have — a grid item defaults to
  `min-width: auto`, meaning it never shrinks to fit its track unless
  told to. The row holding the filename, status badge, and delete
  button was never actually constrained to the card's width, so a long
  filename silently pushed the badge and delete button past the
  card's visible edge. Fixed with one `min-w-0` on that row; reproduced
  with a document named to match the reported screenshot before
  confirming the fix, not just inferred from reading the CSS.
- Tests: 5 new backend (`delete_document_node`'s query and its
  circuit-open propagation; `Document.has_file` and
  `DocumentListItem`'s exposure of it, checked directly rather than
  only by hand as during ADR-044's build) on top of the 9 written
  during the initial build (the cascade-delete integration test that
  caught the missing `await`; `DocumentDeletionService`'s full
  failure-isolation matrix — blob failure, graph failure, no file ever
  stored, a required database failure; `blob_storage.delete_document`'s
  three paths). Backend suite: 119 → 133 passing. Frontend: 5 new for
  `DeleteDocumentButton` (the confirmation dialog, cancelling, a
  successful delete refreshing the list, an error message that keeps
  the dialog open, a 401 redirecting to `/login`) plus updates to
  `DocumentCard`'s existing tests for the new `next/navigation`
  dependency. Frontend suite: 28 → 33 passing.
- Verified live: a real document, including one deliberately named to
  reproduce the layout bug, deleted through the actual confirmation
  dialog — then checked directly, not assumed: zero orphaned rows in
  `chunks` or `document_permissions` across the whole database, the
  blob actually gone from Azurite (confirmed by listing the container's
  contents before and after), and the audit log entry carrying the
  correct deleting `user_id`.

## Scale, cost, and on-call reality
Nothing about this feature adds a new external dependency or a new
recurring cost — it only removes data that was already being paid to
store. The real operational risk is the opposite of ADR-044's: instead
of an orphaned blob accumulating from a failed *upload*, a failed
*delete* cleanup step can now leave one behind on the way out, with the
same honestly-named, low-urgency shape — logged, not silently lost, and
not something a user-facing action can get stuck on. There is currently
no way to recover a deleted document — no soft-delete, no trash, no
undo beyond the confirmation dialog itself. That's a deliberate
consequence of the user's own explicit request ("deleted completely"),
not an oversight, but it is worth naming as the real, permanent
trade-off it is: the confirmation dialog is the only safety net this
feature has.
