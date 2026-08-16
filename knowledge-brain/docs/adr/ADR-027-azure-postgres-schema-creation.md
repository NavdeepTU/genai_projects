# ADR-027: Creating the Azure Postgres schema — a one-time manual step, not automated

## Status
Accepted, verified live. Resolves the standalone gap named in
[ADR-026](ADR-026-api-management-gateway.md)'s "Consequences" section.

## Context
ADR-026 found, as a side effect of verifying the API Management
gateway, that the real Azure Postgres database had never had its
application tables created. Every prior "verified live" Azure
deployment check (`curl backend_url/docs`, the CI/CD smoke test) only
ever exercised a static route that never touches the database, so this
went unnoticed across several sessions of otherwise-real verification.
`documents`, `chunks`, `audit_log`, and `document_permissions` simply
didn't exist; any request that tried to write to `audit_log` — which
includes every rejected request, since both `gateway_secret_middleware`
and `user_id_middleware` log rejections — crashed with
`asyncpg.exceptions.UndefinedTableError`.

## Decision
Fixed directly, with no new automation built around it:
1. A temporary Postgres firewall rule
   (`azurerm_postgresql_flexible_server_firewall_rule.allow_operator`),
   scoped to the operator's own current public IP via a new
   `operator_ip_address` Terraform variable, applied just long enough to
   connect directly.
2. Connected with `psql` and ran `CREATE EXTENSION IF NOT EXISTS
   vector;` inside the real `knowledge_brain` database — the extension
   was already allow-listed at the server level by earlier Terraform
   work, but allow-listing and actually enabling it inside one specific
   database are two separate steps, the same distinction local setup
   already documents.
3. Ran `scripts/create_tables.py` — the exact same script local
   development already uses — against the real Azure connection string,
   passed as a one-off `DATABASE_URL` override rather than changing the
   local `.env` permanently.
4. Removed the temporary firewall rule immediately after, via
   `terraform apply` again, and deleted the now-unused
   `operator_ip_address` variable.

## Reasoning
The firewall opening was scoped as narrowly as possible on purpose —
one specific IP, removed the moment it was no longer needed — rather
than a standing rule or a broader range, since this is a real opening
in a production database's network perimeter, not a cosmetic one.
Reusing `create_tables.py` unchanged, instead of writing a
one-off SQL script, keeps exactly one source of truth for "what the
schema should look like" — the same models `Base.metadata.create_all()`
already reads from for local development.

A real alternative was available and explicitly not taken: building
this into the GitHub Actions CI/CD pipeline, so a schema change would
apply automatically alongside a code deploy, the same way an image
already does. Rejected for now because this project has no real
migration tool — `create_tables.py` only knows how to create tables
that don't exist yet; it has no concept of altering a table that already
exists to match a changed model, which is exactly what a second,
future schema change would need. Automating today's blunt
create-everything-once step into CI would just automate running
something that can't safely handle the next real change anyway,
without solving the actual underlying gap.

## Consequences
- The real Azure Postgres database is now schema-complete and verified
  two ways: `\dt` confirms the four tables exist, and a real request
  through the live API Management gateway now returns the *correct*
  `401` (`"X-User-Id header is required"`) instead of a `500` — the
  clean end-to-end confirmation ADR-026 was blocked from getting.
- Every feature that writes to the database — uploads, queries,
  permission grants — can now genuinely succeed against the deployed
  backend for the first time, not just against local Docker Postgres.
- The firewall is back to its pre-session state; no standing opening
  was left behind.
- A real, still-open gap this incident points at directly: there is no
  migration tool and no automated way to apply a *future* schema change
  to Azure. The next new column or table will need this exact same
  manual sequence — a temporary firewall rule, a direct `psql`/script
  connection, a manual teardown — repeated by hand. A `git push` alone
  will not carry a schema change to production the way it already
  carries a code change.

## Scale, cost, and on-call reality
This is fine, even appropriate, for a solo learning project with no
real users and infrequent schema changes — the manual process is fully
understood, narrowly scoped, and left no residue. It would not survive
contact with a real team or real production traffic: a schema change
that only ships when someone remembers the manual steps is a genuine
outage risk (code deployed expecting a column that was never added),
and a firewall rule opened by hand, even briefly, is an audit and
process gap at any real scale — "did someone remember to close it"
should never be the actual safeguard. The real fix, when this project
gets there, is a proper migration tool (Alembic is the natural choice
given the existing SQLAlchemy models) wired into the same CI/CD
pipeline that already deploys images automatically, so schema changes
and code changes ship together, versioned, without a human ever
touching the database's firewall by hand again.
