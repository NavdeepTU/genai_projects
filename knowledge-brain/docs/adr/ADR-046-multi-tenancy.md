# ADR-046: Multi-tenancy — tenant-wide document sharing, per-user conversations

## Status
Accepted.

## Context
Every document and every user in this system has, until now, belonged
to a single, implicit "everyone" — the only access control that
existed was `DocumentPermission`, a per-user, per-document grant table
introduced for build-order item 8. That model was designed around one
company's own internal users sharing documents individually with each
other; it had no concept of a company at all, let alone more than one.

The actual requirement, stated explicitly at the start of this feature,
was narrower and more common than a general permission system: group
users into companies ("tenants"), share documents fully within a
company, keep conversations private to the individual who started
them, let a user pick their company from an already-registered list at
signup, and let only an admin register a new company. Building that on
top of the existing per-user grant table would have meant maintaining
two overlapping access-control mechanisms indefinitely — one scoped to
a company, one scoped to an individual document — for a permission
model that had no UI to create individual grants with in the first
place (ADR-045 already noted this: sharing had never been exercised in
practice, since no frontend to grant access to a specific user beyond
the uploader has ever existed).

Three real users and thirty-two real documents already existed in the
database before any tenant did, uploaded and created under the old,
tenant-less model. Introducing `tenant_id` as a required column on
`users` and `documents` meant deciding what happens to that existing
data, not just to data created going forward.

## Options considered

**Whether tenant-wide sharing replaces or sits alongside per-user
grants:**
1. **Replace `DocumentPermission` entirely — tenant membership becomes
   the whole access-control mechanism** — the chosen approach. A
   document is visible to every user in the tenant that uploaded it,
   full stop; there is no remaining way to restrict a document to a
   subset of users within a tenant.
2. Keep `DocumentPermission` as an additional, finer-grained layer on
   top of tenant membership — a document could be shared tenant-wide
   *or* restricted to specific users within the tenant. More capable,
   and the only option that would have kept faith with this project's
   own Enterprise Requirement 5 ("multi-tenancy is not enough — users
   should only retrieve chunks from documents they have explicit
   access to"). Rejected for this pass anyway: the requirement as
   stated ("documents are shared within the tenant") describes
   tenant-wide sharing as the goal itself, not a floor with per-user
   restriction layered on top, and keeping a permission system that
   nothing in the product could actually create a *specific* grant
   through (no per-document, per-user sharing UI exists, same gap
   ADR-045 already named) would have meant carrying dead-code risk
   forward indefinitely rather than deleting it.

**What happens to the three users and thirty-two documents that
existed before any tenant did:**
1. **One backfill tenant, created once, named "Microsoft," with every
   existing user and document assigned to it** — the chosen approach.
   A single hand-run SQL migration: create `tenants`, add `tenant_id`
   as nullable to `users` and `documents`, insert the backfill tenant,
   update every existing row to point at it, then make the column
   `NOT NULL` on both tables.
2. Leave `tenant_id` nullable indefinitely and treat `NULL` as its own
   implicit "no tenant" bucket. Avoids a backfill step entirely, but
   turns every tenant-scoped query into a three-way case (this tenant,
   that tenant, or no tenant at all) forever, for a transitional state
   that only ever needed to exist once, at migration time.

## Decision
`Tenant` is a new top-level table (`id`, unique `name`, `created_at`).
`User.tenant_id` and `Document.tenant_id` are both required foreign
keys, set once — at signup for a user, at upload for a document — with
no route that changes either afterward. Document access is now
entirely tenant membership: `DocumentRepository`'s search, list, count,
and get-by-id methods all filter by `tenant_id`, not by any per-user
grant. `DocumentPermission`, `PermissionRepository`, and the
`grant_document_access` route are deleted outright. Conversations stay
exactly as they were — scoped to `user_id`, invisible to anyone else in
the same tenant — since nothing about the stated requirement touched
them. `tenant_id` replaces `user_id`'s former role as the access-control
parameter threaded through the retrieval pipeline (`QueryState`,
`RetrievalService`, `FederatedRetrievalService`); `user_id` is retained
throughout purely for identity — conversation ownership, audit
attribution, LangSmith tracing — a job it keeps doing unchanged. A user
picks their tenant at signup from `GET /tenants` (public, since no
session exists yet at that point); only an admin can register a new one,
via `POST /admin/tenants`. The three pre-existing users and thirty-two
pre-existing documents were migrated into one backfill tenant, named
"Microsoft," via a hand-run SQL migration — this project's established,
Alembic-free convention for every schema change.

## Reasoning
Deleting `DocumentPermission` rather than layering tenant membership on
top of it was chosen for the same reason ADR-045 chose not to build a
real document-ownership model: this project consistently avoids
building or preserving machinery for a scenario nothing in the product
actually exercises. No UI has ever existed to grant one specific user
access to one specific document — the only thing `DocumentPermission`
ever actually recorded was "the uploader has access," which tenant
membership already subsumes entirely. Keeping it would have meant two
access-control systems, one of them permanently unreachable through any
real user action, forever.

That said, this decision does put the system in real, current tension
with this project's own written Enterprise Requirement 5: "Multi-tenancy
(row-level security) is not enough. Within a tenant, individual users
should only retrieve chunks from documents they have explicit access
to." As built, that is no longer true — every user in a tenant can read
every document that tenant owns, with no remaining mechanism to narrow
that further. This was a deliberate, explicit trade-off made for this
feature's stated scope, not an oversight caught after the fact; it is
recorded here plainly because a written requirement that the shipped
system quietly no longer satisfies is a worse outcome than naming the
gap. Reconciling that requirement's language, or building a
document-level restriction *within* tenant-wide access as a later,
separate feature, is future work — not something this ADR resolves.

The single backfill tenant was chosen over a nullable, three-state
`tenant_id` because the "no tenant yet" state only needed to exist for
the duration of one migration, not as a permanent branch every future
query has to account for. Naming it "Microsoft" was a direct choice,
not a default — the alternative (a generic name like "Default" or
"Legacy") would have obscured that this bucket represents real,
specific pre-existing data, not a placeholder.

Two pieces of hardening followed directly from `tenant_id` becoming the
real access boundary, not from any new scope sought out on their own:

- `DocumentGraphService.build_references` used to search every document
  system-wide (`find_by_keyword_unrestricted`) when building Neo4j
  reference edges at ingestion time. Under tenant-wide sharing, an
  unrestricted search could create a reference edge from one tenant's
  document to another tenant's, which `RetrievalService._graph_context_node`
  would then read a snippet from and surface in an unrelated tenant's
  answer — a real cross-tenant leak, closed by scoping the search to
  the ingesting document's own tenant. `find_by_keyword_unrestricted` was
  deleted rather than kept alongside the now tenant-scoped
  `find_by_keyword`, since "unrestricted, within one tenant" and "any
  user's access within that tenant" collapsed into the same query once
  per-user grants were gone.
- As defense in depth, `_graph_context_node`'s own snippet read
  (`get_first_chunk_text`) is independently tenant-scoped too — so even
  if a bad reference edge were ever created by some other path, the
  final read still can't surface cross-tenant content. `tests/test_retrieval_service.py`
  has a regression test for exactly this: a fake graph repository that
  *claims* a cross-tenant reference edge exists, asserting the snippet
  never comes back anyway.
- MCP's `X-User-Id` header used to be pure self-assertion — any UUID-
  shaped string was trusted with zero database check. Every document
  call now needs a real `tenant_id`, and a fabricated user id has none,
  so `user_id_middleware`'s MCP branch now does a real
  `UserRepository.get_user_by_id` lookup and rejects (401) anything that
  doesn't resolve to a real account.

## Consequences
- New: `app/models/tenant.py` (`Tenant` ORM model, `TenantResponse`,
  `TenantListResponse`, `CreateTenantRequest` — with a Pydantic
  validator that strips whitespace and rejects an all-blank name,
  added after code review caught that an untrimmed name could bypass
  the duplicate-name check — `CreateTenantResponse`),
  `app/repositories/tenant_repository.py`, `app/api/tenants.py` (public
  `GET /tenants`, exempted from the auth middleware for the same reason
  `/auth/signup` and `/auth/login` are).
- Deleted: `app/models/document_permission.py`,
  `app/repositories/permission_repository.py`, the
  `grant_document_access` route, the Admin page's permissions viewer.
- `app/repositories/document_repository.py`: every access-scoping
  method rewritten to filter by `tenant_id` — `find_similar_chunks`,
  `find_by_keyword`, `list_domains_for_tenant`,
  `list_documents_for_tenant`, `count_documents_for_tenant`,
  `get_document_for_tenant`, `get_first_chunk_text`.
- `app/core/middleware.py`: a new `_tenant_id` context var and
  `get_current_tenant_id()`; both REST and MCP identity resolution now
  set it alongside `user_id`; `/tenants` added to `AUTH_EXEMPT_PATHS`.
- `app/services/query_graph.py`, `retrieval_service.py`,
  `federated_retrieval_service.py`: `tenant_id` threaded through
  `QueryState` and every retrieval entry point, alongside the
  unchanged, identity-only `user_id`.
- `app/services/document_graph_service.py`: `build_references` scoped
  to the ingesting document's own tenant (the cross-tenant leak fix
  described above).
- `app/api/admin.py`: new `POST /admin/tenants`, with a friendlier
  pre-check for a duplicate name (409) plus a `try/except IntegrityError`
  around the actual insert — added after code review confirmed the
  pre-check alone leaves a real race window where two concurrent
  registrations of the same name could both pass it and the second
  would otherwise surface as an unhandled 500.
- `app/services/auth_service.py`, `app/api/auth.py`: signup validates
  the chosen `tenant_id` against a real, registered tenant
  (`TenantNotFoundError` → 400 if not).
- Frontend: a tenant `<select>` on the signup page (server-fetched via
  `getTenants()`, no client-side proxy needed since it renders
  pre-login), the Admin page's "Tenant management" section rebuilt as a
  real register-and-list UI (replacing its old placeholder), a new
  `components/ui/select.tsx` (a plain styled native `<select>`, not a
  new Shadcn dependency, since the one use case didn't warrant it).
- A pre-existing, unrelated bug in `eval/run_eval.py` was fixed
  alongside this work: `ingestion.create_document` was being called
  with the wrong argument shape, missing the `content: bytes` parameter
  ADR-044 had already added as required — broken since that ADR
  shipped, never caught because the eval harness isn't run in CI.
- Tests: 133 → 150 passing on the backend (17 new — `tenant_repository`
  CRUD; tenant-scoped and cross-tenant-exclusion cases in
  `document_repository`; tenant-aware `auth_service`,
  `ingestion_service`, and `federated_retrieval_service` tests; the two
  cross-tenant graph-leak regression tests described above in
  `document_graph_service` and `retrieval_service`; a Pydantic
  validator test and an `IntegrityError`-to-409 regression test for the
  two bugs code review caught). Frontend suite unchanged at 37 (the
  admin dashboard's tests were restructured, not added to).
- Verified live, not just by test: two independent users signed up into
  the same tenant, confirmed one instantly sees a document the other
  just uploaded, with no grant; a second tenant registered and a third
  user signed into it confirmed at **zero** documents, and a question
  answerable only from the first tenant's data came back "I don't
  know" — the retrieval pipeline itself never touched the other
  tenant's content, not just the document list hiding it.

## Scale, cost, and on-call reality
No new external dependency and no new recurring cost — `tenant_id` is
a plain foreign-key column, and tenant-scoped queries use the same
indexes and query shapes the per-user-scoped ones did before. The real
new cost is on the hottest path in the app: `user_id_middleware` now
opens a fresh database session on every authenticated request purely to
resolve `tenant_id` (previously the MCP path made zero database calls
at all, trusting its header outright), with no caching of the
user-to-tenant mapping. At today's traffic this is invisible; at 10x it
becomes a real, avoidable per-request cost worth caching — the
user-to-tenant mapping changes at most once per user, ever (there is no
route that lets a user change tenants), which makes it about as
cache-friendly as a value can be.

The permanent, named trade-off is the Enterprise Requirement 5 tension
described above: this system, as shipped, does document sharing at the
tenant level only. A company that wants to keep one document restricted
to a handful of people within itself has no way to do that today. That
gap did not exist before this feature (there was no concept of a
company to share *within* at all), but it is a real gap relative to
this project's own stated requirements, and it should be treated as
open, tracked work rather than a closed question.
