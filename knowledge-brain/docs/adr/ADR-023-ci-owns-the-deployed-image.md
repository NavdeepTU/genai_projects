# ADR-023: CI owns the deployed image tag, not Terraform

## Status
Accepted. Extends ADR-022 and the GitHub Actions pipeline built
alongside it.

## Context
GitHub Actions now deploys a new image on every push to `main`, using
`az containerapp update --image ...:${{ github.sha }}` directly against
the Container App. `main.tf` separately declares
`image = "...knowledge-brain-backend:latest"` as part of the same
resource. Left as-is, these two mechanisms disagree about what the
"correct" image is the moment CI deploys anything past the first
`apply` — and a future `terraform apply`, run for a completely
unrelated reason (a new Key Vault secret, a config tweak), would see
that disagreement as drift and silently revert the Container App back
to `main.tf`'s stale `:latest` reference, undoing whatever CI had
actually shipped.

## Options considered
1. **Terraform provisions the Container App once, then explicitly
   stops tracking the image field** (`lifecycle { ignore_changes }`),
   leaving it permanently owned by CI's `az containerapp update` calls
   from that point on.
2. **CI drives every deploy through Terraform itself**
   (`terraform apply -var="image_tag=$GITHUB_SHA"` instead of a direct
   Azure CLI call), making Terraform the single mechanism that ever
   changes the resource, so no two systems can ever disagree.

## Decision
Option 1. Added a `lifecycle` block to `azurerm_container_app.backend`
ignoring `template[0].container[0].image` specifically — no other
field on that resource is affected.

## Reasoning
Option 2 is the more theoretically "correct" answer — a single source
of truth with no drift possible by construction — but it has a real,
blocking cost this project isn't ready to pay: Terraform's state file
is still local, never pushed anywhere. A GitHub Actions runner starts
from nothing every run and has no access to a state file sitting on
one laptop. Running `terraform apply` safely from CI requires a remote
backend first (an Azure Storage account holding `.tfstate`, with
locking), which doesn't exist yet. It would also mean every ordinary
code deploy pays the cost of a full plan/apply cycle instead of one
CLI call, and it would need to grant the CI identity much broader
permissions than the two narrowly-scoped roles (`AcrPush`, `Container
Apps Contributor` on just this one resource) it actually needs today.

Option 1 matches something this project already decided early, before
any of this existed: `ARCHITECTURE.md` already states infrastructure
changes and routine deployments are meant to be two separate concerns,
not one. `ignore_changes` is the direct implementation of that
intent — Terraform keeps owning the Container App's shape (secrets,
env vars, scaling, ingress), CI owns which image is currently running,
and neither one fights the other over it. It's also not a new pattern
for this file: the same mechanism already exists for Postgres's `zone`
field, for an unrelated but structurally identical reason (something
else — Azure itself, in that case — legitimately changes a field
Terraform shouldn't try to fight over).

## Consequences
- `main.tf`'s `image = "...knowledge-brain-backend:latest"` is now
  effectively inert past the very first `apply`. It's what creates the
  resource the first time; it is never enforced again. The real,
  running image from that point on is whatever CI's `az containerapp
  update` last set — a commit SHA, never the literal `latest` tag.
- `ignore_changes` is scoped to that one exact attribute path only.
  Every other field on the same `container` block — `cpu`, `memory`,
  every `env` block — remains fully Terraform-managed, exactly as
  before. A manual or out-of-band change to any of *those* fields
  would still be caught and reverted on the next `apply`.
- This only covers the image field. It does not make deploys any
  safer in themselves — see below.

## Scale, cost, and on-call reality
This only solves *ownership* of the image field, not deploy safety.
The Container App still runs in `revision_mode = "Single"`, which
means a new image — deployed by CI or by anyone — cuts over 100% of
traffic immediately, regardless of how many replicas are running. This
project's own arm64/amd64 incident (ADR-022) is the concrete example:
if this Container App had been running 10 replicas that day instead of
1, all 10 would have failed to pull the broken image at once, same
blast radius, just more instances failing simultaneously rather than
one. More replicas buys capacity, not safety. Real protection against
a bad deploy — a canary that shifts a small slice of traffic to a new
revision before committing fully — would need Container Apps'
`Multiple` revision mode with explicit traffic splitting, a
meaningfully bigger change than this one, and worth naming as
deliberately out of scope here rather than assumed to already exist.
