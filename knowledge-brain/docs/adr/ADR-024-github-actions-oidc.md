# ADR-024: GitHub Actions CI/CD via OIDC federated identity

## Status
Accepted and verified live — `terraform apply` created the identity
and role assignments, the repository variables are set, and the
workflow has completed a full successful run end to end (test → OIDC
login → build → push → deploy → smoke test). Extended by
[ADR-025](ADR-025-ci-cd-first-real-run.md), which covers three more
real bugs found only by actually running this, not by reviewing it.

## Context
The last piece of build-order item 10: automate what today is a
manual `docker build` / `docker push` / `az containerapp update`
sequence, so every push to `main` touching `knowledge-brain/` tests,
builds, and deploys on its own.

## Options considered
For authenticating the pipeline to Azure:
1. **A stored Azure service principal secret**, saved as a GitHub
   Actions secret — the traditional approach, works with any CI
   system, no special Azure AD setup beyond creating the principal.
2. **OIDC federated identity** — GitHub mints a short-lived,
   cryptographically signed token for each workflow run; Azure AD
   trusts that token directly, scoped to an exact trust condition, with
   no credential stored anywhere at rest.

For scoping what the CI identity can actually do:
1. One broad role assignment (e.g. `Contributor` on the whole resource
   group) — simplest to write, works for anything future workflows
   might need.
2. Multiple narrow role assignments, each scoped to exactly one
   resource and one capability (`AcrPush` on the registry only,
   `Container Apps Contributor` on the one Container App only).

## Decision
OIDC federated identity, with two narrowly-scoped role assignments
rather than one broad grant. The federated credential's trust
condition (`subject`) is set to exactly
`repo:NavdeepTU/genai_projects:ref:refs/heads/main` — matching this
project's own repo and the workflow's own `on: push: branches: [main]`
trigger precisely, no broader.

## Reasoning
A stored secret is a real, standing liability the moment it exists:
something that can leak, that needs rotation, that works from anywhere
it's pasted, and that keeps working until someone notices and revokes
it. OIDC removes the credential from the equation entirely — there is
nothing to steal, because nothing is ever stored. This is the same
philosophy Enterprise Requirement 2 already applies to the running
backend (Managed Identity instead of a raw password); OIDC extends
that same idea to the pipeline that deploys it.

The tight `subject` scoping matters independently of OIDC itself: even
if this exact identity's client ID somehow became known, only a
workflow run *on this specific repository's main branch* could
actually authenticate as it — not a fork, not a pull request, not a
different branch. That's a meaningfully smaller blast radius than a
shared secret, which grants access to whoever holds the string,
unconditionally.

The two narrow role assignments follow the same reasoning already
applied everywhere else in this project's Azure setup (the backend's
own Managed Identity has exactly two grants — Key Vault read, `AcrPull`
— nothing broader). A single resource-group-wide `Contributor` grant
would have been faster to write and would never need revisiting as the
project grows, but it would also let a compromised or misconfigured
workflow touch Postgres, Key Vault, or anything else in the resource
group — capability this pipeline has no actual use for. Scoped to just
the registry and just the one Container App, a compromised CI run can
push a bad image and swap a revision — a real but bounded risk — and
nothing more.

## Consequences
- `infra/github_oidc.tf`: `azuread_application`, `azuread_service_principal`,
  `azuread_application_federated_identity_credential`, and two
  `azurerm_role_assignment` resources (`AcrPush`, `Container Apps
  Contributor`).
- `infra/main.tf`: added the `azuread` provider alongside the existing
  `azurerm` one.
- `infra/outputs.tf`: five new outputs (`github_actions_client_id`,
  `github_actions_tenant_id`, `github_actions_subscription_id`,
  `container_registry_name`, `container_app_name`), meant to be read
  via `terraform output` and set as GitHub Actions repository
  *variables*, not secrets — none of these five values are sensitive
  on their own.
- `.github/workflows/knowledge-brain-ci-cd.yml`, at the **monorepo
  root**, not inside `knowledge-brain/` — the only place GitHub
  actually discovers workflow files across this repo's three sibling
  projects. Scoped with `paths: knowledge-brain/**` so it never fires
  on the other two projects' changes. Pipeline: checkout → install
  `uv` → `uv run pytest` as a real gate, stopping here on failure →
  OIDC login → `az acr login` → `docker build --platform linux/amd64`
  (explicit on purpose, directly closing the arm64/amd64 incident from
  ADR-022) → push → `az containerapp update --revision-suffix
  ${{ github.sha }}` → a `curl -f` smoke test against the live URL.
- Code review before ever running any of this caught three real bugs,
  all fixed: a duplicate `data "azurerm_client_config" "current"`
  block that would have failed `terraform validate` outright; a
  doubled `https://` in the smoke test's curl target, since the
  `backend_url` output already includes the scheme; and an image
  repository name (`knowledge-brain`) that didn't match what the rest
  of the project already calls it (`knowledge-brain-backend`), which
  would have deployed successfully but left `main.tf`'s own declared
  image silently out of sync with what CI actually shipped.
- See [ADR-023](ADR-023-ci-owns-the-deployed-image.md) for the
  separate, related decision on how Terraform and this pipeline
  coexist without fighting over the Container App's `image` field
  going forward.
- **Now fully done, verified live:** `terraform apply` created the
  identity and role assignments, all 8 repository variables are set,
  and the workflow has completed a real, successful end-to-end run.
  Build-order item 10 is complete. Getting from "written" to "actually
  passing" surfaced three more real bugs, none visible from code review
  alone — see [ADR-025](ADR-025-ci-cd-first-real-run.md).

## Scale, cost, and on-call reality
OIDC's real payoff shows up in exactly the incident it prevents: a
stored secret leak requires someone to notice, rotate the credential,
and audit everything that credential touched in the meantime — a real
incident with a real cost. A leaked OIDC client ID, by contrast, is
close to useless on its own: without a workflow run on this exact
repo's `main` branch actually requesting a token, there's nothing an
attacker can do with it. This shifts an entire class of "did our CI
secret leak" incident response work into something that structurally
can't happen the same way.

The narrow role scoping has a real, opposite-direction cost worth
naming honestly: every *new* thing this pipeline needs to touch later
(a second Container App, a database migration step) needs its own
deliberate role assignment added, rather than already being covered by
a broad grant. That's the trade-off made here — more upfront and
ongoing Terraform maintenance, in exchange for a CI identity that can
only ever do the specific things it's actually supposed to do.
