# ADR-020: Azure deployment — core infrastructure

## Status
Accepted (for the infrastructure covered here — real infrastructure
exists in Azure and is verified reachable; the broader build-order
item 10, running our actual backend code there, is not complete yet.
See Consequences.)

## Context
Build-order item 10. Chosen deliberately before item 9 (API
Management) — the user identified the dependency themselves: a
gateway needs a real backend to route to, and nothing ran in Azure
yet. Also resolved a real, previously-unaddressed gap in `CLAUDE.md`'s
Azure service mapping, which never actually specified what Neo4j maps
to.

## Options considered
For where Neo4j runs in Azure:
1. **Self-hosted in a container**, on Azure Container Apps, the same
   image already used locally.
2. **Neo4j AuraDB**, a fully managed service outside Azure entirely.

For how Terraform and application deployment relate:
1. **One Terraform run per code change** — the Container App's image
   reference updated and re-applied every time the backend changes.
2. **Two separate concerns** — Terraform manages the Container App's
   existence and shape; a separate process (GitHub Actions, later)
   updates which image it runs.

For the Container App's network exposure, given API Management
doesn't exist yet:
1. **Internal-only ingress** — unreachable from outside the Container
   Apps environment until a gateway exists.
2. **External ingress** — a real public URL, reachable now, with
   nothing in front of it yet.

## Decision
AuraDB for Neo4j. Two separate concerns for Terraform vs. deployment.
External ingress, explicitly temporary.

## Reasoning
AuraDB was chosen over self-hosting Neo4j in a container for the same
reason Postgres uses a managed Flexible Server rather than a
self-run container: this project already prefers managed services over
self-hosted ones once real cloud infrastructure is involved, and
AuraDB's free tier (verified directly against Neo4j's current pricing,
not assumed) matches that pattern exactly, at zero cost. It's signed
up directly at neo4j.com, not through Azure Marketplace, since that
marketplace listing now only offers paid tiers.

Keeping Terraform and deployment as separate concerns avoids a common
early mistake: conflating rare infrastructure changes with frequent
code deployments. The Container App is defined once, pointed at a
placeholder image for now; swapping in the real image and keeping it
updated going forward is deliberately left to GitHub Actions, not
something that requires touching Terraform on every commit.

External ingress was chosen over internal-only after being
deliberately flagged, per `CLAUDE.md`'s own rule to stop and remind
before building something that skips an Enterprise Requirement:
Requirement 1 says the backend should never be exposed directly to
the internet, and external ingress does exactly that until API
Management exists. Internal-only ingress was rejected specifically
because it would have made this entire phase unverifiable — there'd
be no way to confirm the deployment actually worked without a
reachable URL to test against. Accepted as a named, temporary
trade-off, to be tightened the moment item 9 exists, not a permanent
decision.

## Consequences
- `infra/main.tf`, `variables.tf`, `outputs.tf` define: a resource
  group, Log Analytics workspace, Container Apps environment, Postgres
  Flexible Server (Burstable tier, `pgvector` allow-listed), Key
  Vault, a user-assigned Managed Identity with both Key Vault read
  access and (via a separate RBAC role assignment) registry pull
  access, a Container Registry, and the Container App itself —
  currently pointed at a placeholder image (`mcr.microsoft.com/k8se/quickstart`),
  not our own.
- **Real infrastructure now exists in Azure and is verified reachable** —
  not just defined. `terraform apply` succeeded, and the placeholder
  responds with a real `200` at its public URL, confirmed with `curl`,
  not just inferred from a clean `apply` exit code.
- **Deploying our actual backend code is explicitly not done yet.**
  Still needed: a `Dockerfile` (not written), building and pushing a
  real image, updating the Container App's image reference, reverting
  `target_port` from its current temporary value (80, matching the
  placeholder) back to 8000 (our app's real port), and a GitHub
  Actions pipeline to automate that going forward. This ADR covers the
  infrastructure phase specifically, not the full build-order item.
- **Five real, distinct errors were found and fixed live, not
  anticipated in the design** — each with a different, specific root
  cause, verified against real evidence (Azure CLI output, official
  docs, or GitHub issue threads) rather than guessed at:
  1. **Postgres version validation failing with an empty allowed-list.**
     Root cause had nothing to do with the version number — this
     subscription is restricted from provisioning Flexible Server in
     `eastus` at all, confirmed via `az postgres flexible-server list-skus`.
     Fixed by switching the default region to `centralus`.
  2. **A provider bug** ("Provider produced inconsistent result after
     apply... Root object was present, but now absent") on two
     unrelated resources in the same run — a documented, widely-reported
     AzureRM provider issue where a resource is actually created
     successfully in Azure, but the provider's own state-recording step
     fails right after. Fixed by importing both already-existing
     resources into Terraform's state with `terraform import`, rather
     than letting Terraform try to recreate them.
  3. **Availability zone drift on the Postgres server** — Azure manages
     the zone dynamically after creation, which Terraform kept trying
     to "correct" without being told not to. Fixed with a documented
     `lifecycle { ignore_changes = [zone] }` block.
  4. **The placeholder unreachable at first** — `target_port` was set
     to 8000 (our app's real port) while the placeholder image only
     listens on port 80. Temporarily changed to 80 specifically to
     verify the infrastructure itself, with an explicit code comment
     marking it for reversion once the real image replaces the
     placeholder.
  5. **The region change forced a full resource group recreation** —
     expected and understood at the time (a resource group's location
     can't change in place, and every other resource references it),
     not a surprise, but worth naming as a real consequence of the
     region fix, not a separate bug.

## Scale, cost, and on-call reality
This is the first genuinely recurring Azure cost this project has
taken on — Postgres, the Container App, Log Analytics, and the
registry all bill continuously from the moment they exist, unlike the
pay-per-call AI services used everywhere else so far. Kept
cost-conscious deliberately: the cheapest Burstable Postgres tier, a
Basic-tier registry, a single fixed replica.

The subscription's regional restriction on Postgres Flexible Server is
worth remembering as a general lesson, not just this project's
specific fix: a subscription being *allowed* to use a service doesn't
mean it's allowed to use it in *every region* — `az <service> list-skus
--location <region>` is the concrete way to check before assuming a
region will work, not after a confusing error.

The Terraform state-vs-reality mismatches this session (the two
`terraform import` cases) are a real, recurring category of
operational risk with infrastructure-as-code generally, not specific
to this project: if a provider (or a network interruption) causes
`apply` to fail *after* a resource is actually created but *before*
state is recorded, state and reality drift apart, and Terraform's next
plan will be wrong until someone notices and reconciles it by hand,
the way we just did. At real team scale, this is exactly the kind of
thing `terraform plan` in CI, run before every merge, is meant to
catch early — not built here, but a natural next addition once CI/CD
exists.

External ingress with no gateway in front of it is the sharpest
remaining edge from this phase: for as long as it takes to build API
Management, the backend (once real code replaces the placeholder) is
genuinely reachable directly from the internet, with none of this
project's rate limiting, API versioning, or centralized auth
validation in front of it — all of which are meant to live in APIM,
not the application itself. Named and accepted deliberately, not
overlooked, but a real, live gap for exactly as long as item 9 remains
unbuilt.
