# ADR-0001: Development environment

- Status: Accepted
- Date: 2026-07-11

## Context

The host has multiple Python installations, WSL 2, and Docker Desktop. Hermes will deploy to a Linux environment and needs a reproducible PostgreSQL-backed toolchain without depending on Codex runtime caches.

## Decision

- Pin Python 3.12 with `.python-version` and manage the project environment with uv.
- Use Docker Desktop's WSL 2 backend for PostgreSQL and future infrastructure services.
- Keep PostgreSQL in one Compose service; do not maintain parallel Windows and WSL database installations.
- The current Windows workspace remains supported. A later source move to the WSL Linux filesystem must be performed through Git clone, not an ad-hoc directory move.
- Keep the application as a modular monolith until an ADR documents a measured reason to split a service.

## Consequences

- Developers use `uv sync --extra dev` and `uv run` for consistent commands.
- PostgreSQL availability is required for a healthy API.
- Every database change is represented by an Alembic migration.
- Windows and Bash bootstrap/dev scripts provide equivalent entry points.
