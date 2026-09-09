# ADR-047: Retiring the per-document access-control requirement

## Status
Accepted. Extends ADR-046 — does not reverse anything ADR-046 built,
only reconciles the written requirement ADR-046 left in tension with
what actually shipped.

## Context
ADR-046 replaced the per-user `DocumentPermission` grant table with
tenant membership as the whole of document access control: a document
is visible to every user in the tenant that uploaded it, full stop.
That ADR's own Reasoning section named a real, current conflict this
created with `CLAUDE.md`'s original Enterprise Requirement 5, which
read: "Multi-tenancy (row-level security) is not enough. Within a
tenant, individual users should only retrieve chunks from documents
they have explicit access to." As shipped, that statement was no
longer true, and ADR-046 deliberately did not resolve it — it recorded
the gap plainly and left reconciling it as explicit future work,
rather than silently building past a requirement the code no longer
satisfied.

That reconciliation turned out to need no new code at all. Revisiting
it at the start of the next session, the answer was that tenant-level
scoping was always the intended, sufficient design — Decision 1 in
ADR-046's own original design conversation was exactly this: replace
the per-user grant table entirely, not layer tenant sharing on top of
it. The Enterprise Requirement 5 language predates multi-tenancy
existing in this system at all, written when "multi-tenancy" was still
a future, unbuilt item on the build order and the only access-control
mechanism this project had was the per-user grant table itself. The
requirement was never revisited once multi-tenancy was actually
designed, so its wording quietly became a demand for a feature nobody
still wanted, not evidence of a real remaining gap.

## Options considered

**How to close the gap ADR-046 named:**
1. **Retire the per-document restriction requirement itself, since
   tenant-level scoping was always the intended final state, not an
   incomplete step toward it** — the chosen approach. No code changes
   at all; `CLAUDE.md`'s Requirement 5 is rewritten to describe
   tenant-level access control as the actual, sufficient requirement.
2. Build a real per-document restriction *within* a tenant (an
   opt-in "restrict this document to specific people" feature) to
   satisfy the original requirement's literal wording as written.
   Rejected: nothing in this product has ever had a UI to create a
   grant this specific, the same gap ADR-045 and ADR-046 both already
   named — building it now would mean adding real, currently-unwanted
   complexity purely to satisfy a requirement that itself needs
   revisiting, backward from how requirements are supposed to drive
   decisions.

## Decision
`CLAUDE.md`'s Enterprise Requirement 5 is rewritten from "Document-level
access control" to "Tenant-level access control": every document
belongs to exactly one tenant, visible to every user in that tenant
and no one outside it, with no finer-grained per-document restriction
required. Its two downstream cross-references (Requirement 9's
federated retrieval, Requirement 10's conversation-aware retrieval,
both of which cited "document-level ACL filter (requirement 5)") are
updated to match. No application code changes — `DocumentRepository`,
`RetrievalService`, and every other component ADR-046 already built
already implement exactly this.

## Reasoning
This is a requirements change, not a scope cut made after the fact to
justify already-shipped code. The distinction matters: ADR-046 was
built to satisfy an explicit, direct request ("documents are shared
within the tenant"), confirmed by two explicit decisions before any
code was written. Enterprise Requirement 5's stricter wording was
written earlier in this project's life, before multi-tenancy was
designed, and was never checked against the actual multi-tenancy
design once that design existed — an oversight in keeping the
requirements document in sync with real decisions, not a deliberate
choice to under-build against a known requirement. Retiring the
requirement's stricter clause is the honest fix for that oversight:
the requirements document should describe what this system is actually
supposed to do, and what it's actually supposed to do — per the
person who owns that decision — is tenant-level sharing, nothing finer.

## Consequences
- `CLAUDE.md`: Requirement 5 renamed and rewritten; Requirements 9 and
  10's cross-references updated to match.
- `docs/adr/ADR-046-multi-tenancy.md`: Status line updated to note it's
  extended by this ADR.
- No application code, test, or migration changes.
- The remaining, still-open items this doesn't touch: `user_id_middleware`'s
  per-request database round trip to resolve `tenant_id` (an efficiency
  concern, not a correctness one), and everything else already tracked
  on the project's standing remaining-scope list.

## Scale, cost, and on-call reality
None — this is a documentation and requirements change with zero
runtime effect. The only real risk this ADR guards against is a subtler
one: a requirements document that quietly drifts out of sync with what
a project actually decided to build, so that a future session (or a
future engineer, or an interviewer reading this project's own ADRs)
reads Requirement 5 and reasonably concludes real work is still owed,
when in fact the requirement itself was the stale part.
