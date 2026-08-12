# ADR-021: Containerizing the backend — Dockerfile and ACR

## Status
Accepted (for the container image itself — built, run, and verified
live, and confirmed pushed to Azure Container Registry. The Azure
Container App is not yet running this image; see Consequences.)
Extended by ADR-022, which deploys this image for real and covers
what broke along the way.

## Context
Build-order item 10, continuing from ADR-020's infrastructure phase.
The Container App has existed and been reachable since last session,
but only running a public placeholder image. This phase covers turning
this project's own FastAPI backend into a real, runnable container
image, and getting it somewhere Azure can actually pull it from.

## Options considered
For the build strategy:
1. **A single build stage**, copying dependency files before app code
   to get Docker layer caching, no separate build/runtime split.
2. **A multi-stage build**, compiling in one stage and copying only
   the finished artifacts into a leaner final stage.

For which user the container runs as:
1. **Root** (Docker's default, nothing extra required).
2. **A dedicated non-root user**, created and switched to explicitly.

For local iteration speed while developing:
1. **Live-reload dev mode** — bind-mounting local source into a
   locally running container, with `uvicorn --reload` watching for
   changes.
2. **Rebuild on every change** — the plain, no-extra-tooling default.

## Decision
Single-stage build, with the dependency-install layer split from the
app-code layer for caching. Runs as a dedicated non-root user. No dev
live-reload mode built this session — named as a real option, not
implemented.

## Reasoning
A multi-stage build earns its keep when a project has a genuinely
heavy build step whose tools and intermediate artifacts shouldn't ship
in the final image — compiling C extensions, a separate frontend
bundle step, and similar. This project has neither: `uv sync` installs
pure Python packages against an already-slim base image, so a second
stage would add complexity without shrinking anything real. Single-stage,
kept lean through `.dockerignore` and layer ordering, was enough.

Running as a non-root user is a standard container security practice,
not a response to any specific incident here — if the app or a
dependency is ever compromised, the attacker inherits an ordinary
user's limited permissions instead of root's, which is one meaningful
step short of a full container escape. Cheap to add, no real downside
for this app, so it was included from the start rather than deferred.

Live-reload dev mode was discussed but deliberately not built this
session — it solves a real friction point (rebuilding an image for
every tiny local change), but it's a local-only convenience, unrelated
to anything actually shipping to Azure, and nothing currently blocks
development without it. Worth adding later if the rebuild cycle
becomes genuinely painful, not before.

## Consequences
- `Dockerfile`: `python:3.12-slim` base, `uv`'s binary copied in
  directly from Astral's own image rather than installed via pip,
  dependency files copied and `uv sync --frozen --no-install-project`
  run before application code is copied in (so the dependency layer
  only invalidates when `pyproject.toml`/`uv.lock` themselves change),
  then a non-root `appuser`, then `uvicorn app.main:app --host 0.0.0.0
  --port 8000` — matching this project's actual convention rather than
  the `fastapi run` CLI shown in Astral's own examples, since
  `pyproject.toml` never added the `fastapi[standard]` extra.
- `.dockerignore`: excludes local Python artifacts, `.env` (and
  `.env.example`), `.git`, and everything not needed at runtime
  (`tests/`, `docs/`, `infra/`, `eval/`) — kept as a blanket safety net
  for the whole build context, not reliant on any one `COPY` line's
  own targeting.
- **A real bug, found only by running the built image, not by
  reviewing the Dockerfile or `.env`:** `.env`'s `OPENAI_API_KEY` line
  was wrapped in double quotes. `python-dotenv` (used when running the
  app directly) strips surrounding quotes automatically; Docker's
  `--env-file` flag does not — it passes everything after the `=`
  completely literally. The container-only symptom was an
  `openai.AuthenticationError: 401`, with the literal `"` character
  visible at the start of the masked key in the traceback. Diagnosed
  by comparing a direct local run (worked) against the same `.env`
  file inside the container (failed) — same file, two different
  parsers, two different outcomes. Fixed by stripping the quotes from
  `.env` directly.
- **The image is verified working end-to-end, locally:** built with
  `docker build`, run with `docker run` against the already-running
  `docker compose` Postgres and Neo4j (reached via
  `host.docker.internal`, since a bind mount or `localhost` inside a
  container never reaches the host the way it does on the host
  itself), and confirmed with a real `/query` call returning a genuine
  LangGraph-generated answer, not just a boot without crashing.
- **Pushed to Azure Container Registry and confirmed there** —
  `az acr repository list` shows `knowledge-brain-backend` really
  present, not just a clean `docker push` exit code.
- `infra/main.tf` updated to reference this real image
  (`${azurerm_container_registry.main.login_server}/knowledge-brain-backend:latest`)
  and reverted `target_port` from its temporary `80` back to `8000` —
  but **`terraform apply` has not been run with this change yet.** The
  Container App in Azure is still running the placeholder as of this
  session's end. Deliberately held back: the Container App currently
  defines zero environment variables, so applying this change as-is
  would very likely deploy a container that crash-loops on startup
  (`pydantic-settings` requires several values with no defaults) —
  something `terraform apply`'s own success/failure signal would never
  reveal, since it only confirms the resource was updated, not that
  the process inside it stayed alive. Key Vault wiring (secrets +
  `env` blocks on the Container App) is the next piece, in progress —
  only the new Terraform variables for real secret values have been
  written so far, not yet the access policy, the `azurerm_key_vault_secret`
  resources, or the Container App's `secret`/`env` blocks themselves.

## Scale, cost, and on-call reality
Layer caching isn't just a build-speed nicety here — at real team
scale, with CI rebuilding an image on every merge, an uncached
dependency layer means every single commit re-downloads and
reinstalls every package, even ones that change once a month. Ordering
`COPY` steps by how often their inputs actually change is a small
decision with a real, compounding cost if gotten backwards.

The `.env`-quoting bug is a good, concrete example of a broader
category worth naming in an interview: configuration that "looks
identical" can behave differently across two different consumers of
the same file, because each one parses it with different rules. The
generalizable lesson isn't "don't quote your env values" — it's that
config correctness can't be verified by reading the file; it has to be
verified against the actual thing consuming it, in the actual
environment it will run in. This project's whole pattern of live
verification over trusting code review exists for exactly this
reason, and this bug is one of its clearest examples yet.

Holding back `apply` until Key Vault wiring is done is itself a small
on-call judgment call worth naming: it would have been faster to just
run `apply` now and debug the resulting crash-loop from logs
afterward, but that trades a fast, cheap failure now (caught here, in
review, before touching Azure) for a slower, more confusing one later
in a real deployment, using Application Insights to figure out why a
"successfully deployed" revision has zero healthy replicas.
