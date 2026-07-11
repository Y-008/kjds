# Hermes repository instructions

## Runtime

- Use the project-local uv environment and Python 3.12.
- Run Python commands through `uv run`; do not use Codex bundled Python as the project interpreter.
- Keep PostgreSQL in Docker Compose. Do not install or start a second host/WSL PostgreSQL for this project.
- Do not add Redis, Kafka, Kubernetes, Temporal, vector databases, or local model runtimes until an accepted ADR introduces them.

## Architecture

- Keep business logic inside domain/application services; Agents and connectors may not write repositories directly.
- External providers must implement connector/provider protocols.
- High-risk actions require approval and audit records.
- Monetary calculations use `Decimal`, explicit currency, FX rate/date, and evidence references.
- Every schema change requires an Alembic migration.

## Quality gates

Before finishing a code change, run:

```text
uv run ruff check .
uv run pytest
```

For database/API changes also run PostgreSQL, migrate to head, and verify `/health`.

## Safety

- Never commit `.env`, credentials, bank information, platform secrets, database dumps, or customer data.
- Do not delete or overwrite user documents and media in this repository.
- Preserve existing user changes and avoid destructive Git operations.
