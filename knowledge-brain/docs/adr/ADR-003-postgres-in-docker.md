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
