# ADR-003: Run Postgres in Docker, not installed directly on the machine

## Status
Accepted

## Context
The project needs a Postgres database with the pgvector extension enabled
for local development. It could either be installed directly on the
developer's machine, or run as a containerized service via Docker.

## Options considered
1. **Docker (docker-compose.yml)** — Postgres runs inside a container,
   isolated from anything else installed on the machine.
2. **Native install** — Postgres is installed directly via a package
   manager (e.g. Homebrew) and runs as a system service.

## Decision
Run Postgres in Docker (Option 1).

## Reasoning
A native install becomes part of the machine's own environment and can
silently conflict with other software. We hit this directly during setup:
a native Postgres already running on the development machine was bound to
port 5432 and intercepted connections meant for our containerized
database, with no obvious error message — it just connected to the wrong
database entirely. Docker keeps our project's Postgres fully isolated,
avoids that class of conflict, and means anyone can get the exact same
database version and setup with one command, with no manual install steps.

## Consequences
- Requires Docker Desktop to be running before the app can connect to the
  database — a new local dependency.
- Our Postgres runs on host port 5433, not the default 5432, to avoid
  colliding with any natively installed Postgres.
- Data lives in a named Docker volume; deleting that volume (e.g. via
  `docker compose down -v`) wipes all local data, which is expected for a
  dev environment but worth remembering.

## Scale, cost, and on-call reality
This decision is scoped to local development only, and doesn't carry
forward to production — the target there is Azure Database for PostgreSQL
Flexible Server, which is neither a native install nor our own Docker
container, so this ADR becomes moot the moment real deployment happens.

The actual value here isn't performance, it's drift prevention. A native
install's Postgres version can silently change underneath the project —
a Homebrew upgrade, an OS update — with no record of when or why. Docker
pins an exact version in `docker-compose.yml`; any change to it is a
visible line in a diff and a git commit, not a silent surprise discovered
during an on-call incident. That's a concrete debugging-time cost avoided,
not a hypothetical one — the port-5432 collision that motivated this ADR
in the first place cost real setup time before its cause was clear.

Cost is zero either way locally — Docker Desktop is already a standard
dev tool with no incremental spend. There is no equivalent "on-call"
concern for a laptop-only database; the operational stakes only become
real once Azure Database for PostgreSQL is the target, at which point
this decision is superseded, not extended.
