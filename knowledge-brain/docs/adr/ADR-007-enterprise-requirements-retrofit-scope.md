# ADR-007: Which new "enterprise requirements" to retrofit now, and which to defer

## Status
Accepted

## Context
The project's `CLAUDE.md` was replaced with a version that lists 8
"Enterprise Requirements" as non-negotiable and "built in from the start
— not added later": API Gateway (APIM), Managed Identity/Key Vault
secrets, correlation IDs, PII detection, document-level ACL, an
append-only audit log, circuit breakers, and Terraform resource tagging.

Two features (ingestion, retrieval) were already built and shipped before
this change, under the previous "start simple, add complexity when
needed" philosophy documented in ADR-001 through ADR-006. This created a
direct question: retrofit the existing features to meet all 8
requirements immediately, or not?

## The contradiction that shaped this decision
The new `CLAUDE.md`'s own **Build order** section — which explicitly says
"do not skip ahead" — still lists PII detection as step 7 and
document-level access control as step 8, after hybrid search, reranking,
LangGraph, and the Neo4j graph. This directly conflicts with the
Enterprise Requirements section's "built in from the start" language for
those same two items.

## Options considered
1. **Full retrofit now** — implement all 8 requirements against the
   existing two features before building anything else.
2. **Defer everything** — treat all 8 as applying only to future
   features, changing nothing about what's already built.
3. **Split by actual applicability** — retrofit only the requirements
   that are genuinely self-contained and don't depend on work that
   doesn't exist yet; defer the rest to their natural point in the build
   order or deployment.

## Decision
Option 3 — split by applicability:

- **Defer to their existing build-order steps:** PII detection (step 7),
  document-level ACL (step 8). ACL specifically is meaningless right now
  — there is no user or auth model at all yet to attach permissions to.
- **Defer until actual Azure deployment happens:** API Gateway via APIM,
  and Key Vault/Managed Identity secrets. Both describe how the system
  runs in Azure; the system currently runs entirely locally, so neither
  applies yet.
- **Add now:** correlation IDs, the append-only audit log, and circuit
  breakers. None of these require a new subsystem or an unmade design
  decision — they're self-contained additions to code that already
  exists, and retrofitting them now avoids having inconsistent
  old-vs-new code as more features get built on top.

## Reasoning
Retrofitting PII detection or ACL now would mean literally skipping ahead
to build-order steps 7 and 8 before reaching step 3 — which the file's
own rules forbid. Building ACL specifically before any auth/user model
exists would mean designing access control on top of nothing, likely
requiring a rebuild once real auth is added later anyway. APIM and Key
Vault are deployment-environment concerns with no meaning in a
local-only system. Correlation IDs, audit logging, and circuit breakers,
by contrast, are cheap, additive, and useful immediately regardless of
what gets built next — the same "add real value now, not speculative
scaffolding" reasoning behind every prior ADR.

## Consequences
- Ingestion and retrieval will gain correlation IDs, an audit log entry
  point, and circuit breakers on their external calls, without a broader
  rewrite.
- PII detection and ACL remain explicitly un-built until their designated
  build-order steps are reached — revisit this ADR if the build order
  itself changes.
- APIM and Key Vault remain moot until an actual Azure deployment is
  planned — revisit at that point.

## Scale, cost, and on-call reality
This ADR is a scoping decision, not a scale one, but it carries a real
ownership question worth naming honestly: in a real company, deferring
PII detection isn't a pure engineering call. Shipping a document-upload
feature without PII detection is a risk-acceptance decision with actual
legal exposure — the kind of thing that needs explicit sign-off from
compliance or legal, not just an engineer's judgment that "auth doesn't
exist yet so ACL can wait." On this project, that call is made
unilaterally because it's a single-developer learning project with no
real user data at stake; in a production system, the honest answer to "who
approved deferring this" needs to be a name, not "the developer decided."

The three items built now (correlation IDs, audit log, circuit breakers)
were chosen partly *because* they're the cheapest to retrofit — none of
them required designing around a system that doesn't exist yet (unlike
ACL, which needs an auth model, or APIM, which needs an actual deployed
gateway). That "retrofit cost" lens, not just "is it required," is what
actually separated the two piles.
