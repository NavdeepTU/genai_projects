# ADR-022: Deploying the real backend image — platform target and stable URLs

## Status
Accepted. Extends ADR-021, closing out the deployment it deliberately
left unfinished.

## Context
ADR-021 got the backend built into a real container image, verified
locally, and pushed to Azure Container Registry — but held back
`terraform apply` on purpose, since the Container App had zero
environment variables configured at the time and applying blind would
likely have produced a silent crash-loop with no useful signal from
`terraform apply` itself.

This session filled in the missing Key Vault secrets and Terraform
variables and ran `terraform apply`. It succeeded cleanly — "Apply
complete! Resources: 8 added, 1 changed" — and yet the real backend
was still not reachable for over an hour afterward. Tracing that down
took a real diagnostic chain: revision list, replica status, Log
Analytics console logs, an ACR role-assignment cross-check, and
finally an ACR manifest inspection, before finding the actual cause.

## Options considered
For trusting the deployment was actually working:
1. Treat `terraform apply`'s success output as proof the app is live.
2. Independently verify against the running app — real HTTP requests,
   real revision health state — before calling it done.

For which CPU architecture to build the Docker image for:
1. Let `docker build` default to the host machine's own architecture
   (arm64, on this Apple Silicon Mac).
2. Explicitly target `linux/amd64`, the architecture Azure Container
   Apps actually runs on.

For how `outputs.tf` computes `backend_url`:
1. `azurerm_container_app.backend.latest_revision_fqdn` — a specific
   revision's own address, embedding that revision's name.
2. `azurerm_container_app.backend.ingress[0].fqdn` — the app-level
   address, which always resolves to whichever revision currently
   holds live traffic.

## Decision
Verified the deployment independently rather than trusting Terraform's
exit status. Rebuilt and pushed the image with `--platform linux/amd64`
set explicitly. Changed `backend_url` to use `ingress[0].fqdn`.

## Reasoning
Terraform's success signal only confirms the API calls to update Azure
resources succeeded — it says nothing about whether the process inside
the container actually started and stayed alive. ADR-021 already named
this exact risk before it happened; this session is the case where it
actually did, and it held for over an hour without any error from
Terraform itself.

The arm64 image is a specific trap for Apple Silicon: `docker build`,
`docker push`, and `az acr repository list` all completed without a
single warning, because none of them check whether an image's
architecture matches where it's actually meant to run — that check
only happens at the one place that tries to run it, which is exactly
why nothing caught it earlier in the pipeline.

The revision-pinned URL made this outage harder to see than it needed
to be. Every earlier `curl` against `backend_url` was hitting a
hostname permanently tied to one specific revision — no fix deployed
afterward could ever change what that URL returned, which produced a
false signal that nothing had improved even after real progress had
been made.

## Consequences
- Every future image build for this project needs `--platform
  linux/amd64` set explicitly — worth capturing in a build script or
  `Makefile` target eventually rather than relying on memory, since
  the tooling's default is silently wrong for this specific machine.
- `infra/outputs.tf`'s `backend_url` now always reflects whichever
  revision is actually live, not whatever existed at the last
  `terraform apply`.
- Found along the way, not a code change but worth remembering: `az
  role assignment list -o table`'s `Principal` column falls back to
  showing a service principal's client ID when Azure AD can't resolve
  a friendly display name. The authoritative field is the raw
  `principalId` in JSON output — the table view cost real time here
  chasing a permissions problem that didn't exist.
- The diagnostic sequence used this session — revision list, then
  replica status for `runningStateDetails`, then Log Analytics console
  logs, then a role-assignment cross-check, then an ACR manifest
  architecture check — is a reusable checklist for "deployed but not
  actually working" on this project. Worth writing down properly
  rather than re-deriving live next time.

## Scale, cost, and on-call reality
This exact bug disappears structurally once build-order item 12's
GitHub Actions CI/CD lands: a GitHub-hosted runner builds on amd64
hardware natively, so there's no architecture mismatch possible in the
first place. That's a concrete argument for CI-driven builds beyond
convenience — this class of bug is specific to a manual,
local-machine build-and-push workflow.

A revision that's deployed but silently unhealthy, sitting behind a
healthy fallback revision, is easy to miss in a dashboard that just
shows "Running: true" — `provisioningState` only reflects whether
Azure's API call succeeded, not whether the app inside is actually
serving traffic. At real team scale this needs an actual
availability check — an Application Insights probe hitting a real
`/health` endpoint (which this app doesn't have yet) — rather than
relying on provisioning state or a human noticing a stale response.
