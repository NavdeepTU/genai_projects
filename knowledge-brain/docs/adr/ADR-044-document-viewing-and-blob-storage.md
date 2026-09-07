# ADR-044: Viewing an uploaded document, and Blob Storage

## Status
Accepted.

## Context
The Document Library page (ADR-029) has always let a user upload and
track a file's ingestion progress, but never let them look at the file
itself. Investigating this request surfaced something more fundamental
than a missing button: `IngestionService.process_document` reads a
file's bytes into memory, extracts and chunks its text, then discards
the original bytes entirely — nothing has ever persisted the file
itself, only what it says. This was already a known, named gap (see
ARCHITECTURE.md's "what could go wrong" section, written during the PII
review-workflow discussion), just never one anyone had asked to close
until now.

"Let the user view a document" therefore split into two real pieces:
start actually saving the original file somewhere retrievable, and
serve it back through a permission-checked route.

## Options considered

**Where to persist the original file:**
1. **Azure Blob Storage** — the chosen approach, and this project's own
   stated plan since `CLAUDE.md`'s very first tech-stack section. Real,
   matches production, survives the backend Container App scaling to
   zero (ADR-035) the way a local disk never would.
2. A local folder or Docker volume. Fast to build, but doesn't match
   how the actual deployed backend runs, and breaks the moment the
   container scales down and back up.
3. Store the bytes directly in a Postgres column. No new
   infrastructure, but stores binary files in the relational database
   for no reason other than convenience, and contradicts the project's
   own stated storage plan.

**How local development reaches Blob Storage:**
1. **Azurite (Microsoft's official Blob Storage emulator, run in
   Docker)** — the chosen approach, consistent with how Postgres,
   Neo4j, and Redis already work in this project: a local container
   standing in for the real Azure-managed service.
2. Point local development at the real Azure Storage Account too.
   Fewer moving parts locally, but breaks the pattern every other piece
   of infrastructure here follows, and makes local testing depend on
   network access to Azure.

**How the real deployment authenticates to Blob Storage:**
1. **The backend's own Managed Identity, granted the `Storage Blob Data
   Contributor` role directly on the storage account (RBAC)** — the
   chosen approach. No connection string, no key, no Key Vault secret
   at all — `DefaultAzureCredential` picks the role up automatically.
2. A connection string (with an embedded account key) stored as a Key
   Vault secret, the same pattern already used for `database_url` and
   `neo4j_password`. Consistent with existing precedent, but Postgres
   and Neo4j need this pattern because neither speaks Azure AD auth at
   all — Blob Storage does, so choosing the key-based path here would
   have been settling for a weaker option than the service actually
   supports.

## Decision
Documents are saved to Azure Blob Storage the moment they're uploaded —
synchronously, inside `IngestionService.create_document`, before the
background extraction/chunking/embedding pipeline ever starts. A failed
blob save degrades gracefully: the document row and its access grant
still succeed, the background pipeline still runs, the document simply
has nothing to view (`has_file: false`) until re-uploaded. Local
development uses Azurite; the real deployment authenticates via the
backend's Managed Identity directly against the storage account, no
secret involved anywhere. A new `GET /documents/{id}/content` route
serves the file back, gated by the exact same `get_document_for_user`
permission check every other document-access path in this project
already uses.

## Reasoning
Uploading synchronously, not in the background task, follows the same
split ADR-030 already drew for document creation itself: the row,
domain tags, and access grant are all "fast enough to finish before the
response goes out," while extraction, PII checking, chunking, and
embedding are not. A single blob upload is closer in cost to the first
group than the second — and doing it there means a document is
viewable the instant it's uploaded, even while still processing,
instead of waiting on a background job that has nothing to do with
whether the file itself was saved.

Graceful degradation on a blob-upload failure, rather than failing the
whole upload, follows the same resilience pattern this project applies
everywhere an external dependency sits behind a circuit breaker —
reranking, graph context, domain classification all degrade capability
rather than cascade into a hard failure. Being able to view the file
later is additive to what this system exists to do (answer questions
from it); it was never worth making core ingestion depend on it.

RBAC over a Key Vault-stored connection string was chosen specifically
*because* it was available here and wasn't for Postgres or Neo4j —
passwordless, Managed-Identity-only access is the actual end state
ADR-020's Managed Identity requirement is reaching for, and Blob
Storage is the first service in this project able to satisfy it
without any secret existing anywhere in the app's configuration at all.
One related hardening was deliberately *not* taken this session, named
rather than silently skipped: disabling account-level shared-key access
entirely (`shared_access_key_enabled = false`) would be a stronger
lock, but the Terraform provider itself currently authenticates
container-management operations with the account's key by default —
flipping this off would break `terraform apply` unless the provider is
also switched to Azure AD auth and the operator's own identity granted
a role, a bigger change than this feature's scope.

## Consequences
- `app/models/document.py`: new `storage_path` column (nullable — null
  for anything uploaded before this feature, or if its blob save
  failed) and a `has_file` property the frontend reads to decide
  whether to show a working link or an honest "Not viewable" state.
- `app/core/blob_storage.py` (new): `upload_document`/`download_document`,
  wrapped in their own circuit breaker, plus `ensure_container_exists`
  (called once at startup, Azurite-only — the real deployment's
  container is provisioned by Terraform ahead of time, and the
  backend's Managed Identity isn't granted permission to create one).
  `_build_client` chooses connection-string auth (Azurite) or Managed
  Identity (`DefaultAzureCredential` against the real account) based on
  which setting is populated.
- `app/services/ingestion_service.py`: `create_document` now takes the
  file's raw bytes, uploads them, and records the resulting
  `storage_path` — shared `CONTENT_TYPES` mapping tags the blob at
  upload time and sets the response header when it's served back later,
  so a file is never re-derived and risking drift from what it was
  tagged with.
- `app/api/documents.py`: new `GET /documents/{id}/content`, permission
  checked, `Content-Disposition: inline` so a PDF or text file renders
  in the browser instead of downloading.
- `infra/storage.tf` (new): the Storage Account (`allow_nested_items_to_be_public
  = false`, defense in depth beyond the container's own `private`
  setting), the private container, and the RBAC role assignment.
  `infra/main.tf`: two new plain (non-secret) env vars on the Container
  App.
- `docker-compose.yml`: a new `azurite` service, blob-only.
- Tests: 9 new for `blob_storage.py` (the dual auth-path branching,
  upload/download re-raising on a real Azure failure, the
  container-already-exists no-op), 2 new for `create_document`'s blob
  save and its graceful-degradation path, existing `IngestionService`
  tests updated for the new `content` parameter. Backend suite: 110 →
  119 passing. Frontend: `DocumentCard` tests cover both the working
  link and the "Not viewable" state. 26 → 28 passing.
- Verified live: existing documents (uploaded before this feature)
  correctly show "Not viewable"; a freshly uploaded document's "View"
  link was confirmed to actually serve the real file — fetched from
  Azurite through the new route and proxy, rendered inline in the
  browser with the correct content type — and the database's own
  `storage_path` column was checked directly to confirm it matched the
  blob name the backend actually wrote.

## Scale, cost, and on-call reality
At this project's actual scale — a handful to a few hundred small
documents — Blob Storage costs a few cents a month at most; this was
priced out with the user before committing to the option, not assumed.
The real operational cost is a second external dependency now sitting
in the upload path, with its own circuit breaker and its own honestly-
named degradation mode (documented and tested: an outage there means
"nothing to view," never a failed upload). Every document uploaded
before this feature shipped has no file to show and never will — there
was nothing left to migrate, since the bytes were already gone by the
time this ADR was written. RBAC-based Managed Identity access means
there is, for the first time in this project, an external Azure
dependency with zero secret material anywhere in Key Vault, application
config, or `.env` — a real, if narrow, reduction in what a leaked
config file could ever expose.
