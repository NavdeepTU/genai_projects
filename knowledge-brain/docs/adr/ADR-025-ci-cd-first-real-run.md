# ADR-025: Getting the CI/CD pipeline to actually pass — three real bugs

## Status
Accepted, verified live. Extends [ADR-024](ADR-024-github-actions-oidc.md).

## Context
ADR-024's design was written, reviewed, and passed code review before
ever running. `terraform apply` created the real OIDC identity, the 8
GitHub Actions repository variables were set from `terraform output`,
and the workflow was triggered for the first time. It failed three
times in a row, each on a different step, each for a reason no amount
of reading the YAML or the Terraform would have caught — every one of
these only existed once the pipeline actually ran somewhere that
wasn't this laptop.

## The three failures, in the order they were hit

**1. `Run tests` — `pydantic_core.ValidationError`, 9 missing fields.**
`Settings` requires 9 environment variables with no defaults, normally
supplied by `.env` locally. `.env` is gitignored on purpose and has
never existed on any CI runner. `tests/conftest.py` imports
`app.core.database`, which calls `get_settings()` at module import
time — so even a test with nothing to do with Neo4j or PII detection
still needs all 9 fields present just to get past that import.

**2. `Azure login (OIDC, no stored secret)` —
`AADSTS700213: No matching federated identity record found`.**
The federated credential's `subject` was configured as the plain
`repo:NavdeepTU/genai_projects:ref:refs/heads/main`. The actual OIDC
token GitHub presented had a different subject entirely:
`repo:NavdeepTU@35778181/genai_projects@1321286864:ref:refs/heads/main`
— GitHub includes immutable numeric organization and repository IDs
alongside the names, a real security feature that protects against a
renamed or transferred repository inheriting trust that was meant for
the original one. Nothing about ADR-024's design was wrong; the
subject format it was written against simply wasn't the one this
account's tokens actually use.

**3. `Deploy new revision` — `ContainerAppInvalidRevisionName`.**
`az containerapp update --revision-suffix ${{ github.sha }}` used the
full 40-character commit SHA. Combined with the Container App's own
name (`knowledge-brain-dev-backend`, 27 characters), that's 69
characters — past Azure's 54-character combined limit for a revision
name. A second, latent issue sat in the same constraint: a revision
name must start with a letter, and a raw hex SHA can just as easily
start with a digit — it happened not to matter on this particular
commit, but the next one could have failed the exact same way for a
different reason.

## Decision
Fixed each in place, in the order they were found:
1. Added a `services:` Postgres container (`pgvector/pgvector:pg16`,
   matching the local `docker-compose.yml` image exactly) to the
   workflow, scoped to just the `test-and-deploy` job, with a health
   check and a `knowledge_brain_test` database pre-created. Added a
   step enabling the `vector` extension in it — the same one-time step
   `README.md` already documents for local setup, just automated.
   Added `env:` on the `Run tests` step only: a real `DATABASE_URL`
   pointing at that ephemeral container, and plain placeholder values
   for the other 8 fields, since nothing in the current test suite
   makes a real, unmocked call to Neo4j, OpenAI, Voyage, or Azure
   Language.
2. Updated `github_oidc.tf`'s `subject` to the exact ID-suffixed value
   Azure's own error message reported, rather than guessing at the
   correct format from documentation.
3. Changed `--revision-suffix` from `${{ github.sha }}` to
   `run-${GITHUB_SHA:0:8}` — always under the length limit regardless
   of app name, always starts with a letter, always ends with an
   alphanumeric character, for any possible commit SHA.

## Reasoning
None of these three were guessed at. Each was diagnosed from the
literal error text a real run produced — the missing-fields list from
`pydantic`, the exact rejected subject string from Azure AD, the exact
character-count complaint from the Container Apps API — the same
evidence-first approach this project has used for every other real
incident (ADR-020's Postgres region restriction, ADR-022's
`ImagePullBackOff`). None of the three would have been caught by
reading `github_oidc.tf` or the workflow YAML more carefully; all
three only exist at the boundary between this project's code and the
real systems running it — a CI runner with no `.env`, this specific
GitHub account's actual token format, Azure's specific naming rules.

The test-environment gap is also the concrete argument for why CI
tests need real infrastructure, not just faked calls, extended one
step further than it had been: this project already chose a
real-database/faked-external-API testing strategy specifically because
real bugs were only catchable against a real database. Running that
same test suite for the first time somewhere that wasn't a laptop with
`docker compose` already running proved the same point again, one
layer up the stack.

## Consequences
- The CI test job now depends on a working ephemeral Postgres
  container rather than assuming a `.env` file's existence — a
  meaningfully different (and more correct) assumption than local
  development ever had to make explicit before.
- The 9 dummy environment values in the workflow are placeholders,
  not real credentials — safe to leave in plain text in the YAML.
  Should the test suite ever grow to make a real, unmocked external
  call (a genuine Neo4j integration test, for instance), those specific
  values would need to become real ones, likely via GitHub Actions
  secrets rather than hardcoded strings at that point.
- `github_oidc.tf`'s `subject` now hardcodes this account's specific
  numeric organization and repository IDs. These don't change under
  normal operation — only a repository transfer or similar would
  invalidate them, which is exactly the scenario this ID-inclusion
  feature exists to protect against in the first place.
- Build-order item 10 (Azure deployment via Terraform + GitHub Actions
  CI/CD) is now complete, verified with a real, successful, unassisted
  end-to-end run.

## Scale, cost, and on-call reality
Every one of these three failures would have been caught by a single
real run against a real GitHub Actions environment *before* this was
ever considered "done" — which is exactly what happened here, just
compressed into one debugging session instead of surfacing gradually
across a team's first few weeks using a newly written pipeline. The
generalizable lesson for any CI/CD pipeline, not just this one: code
review and reading YAML catch a real and meaningful class of bugs (the
three fixed in ADR-024 before ever running anything), but a whole
different class only exists at the boundary between the pipeline and
the actual external systems it depends on — an ephemeral test
environment, an identity provider's exact token format, a cloud
platform's specific naming constraints. A pipeline isn't "done" until
it has actually run successfully somewhere real, the same standard
this project already holds every other feature to.
