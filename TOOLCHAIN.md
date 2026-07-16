# Hermes toolchain

## Pinned baseline

| Component | Baseline |
|---|---|
| Python | 3.12, selected by `.python-version` |
| Package/environment manager | uv |
| API | FastAPI + Uvicorn |
| Validation | Pydantic 2 |
| Database | PostgreSQL 17 in Docker Compose |
| Database access | SQLAlchemy 2 + psycopg 3 |
| Migrations | Alembic |
| Tests | pytest and unittest-compatible tests |
| Lint/format | Ruff |
| Containers | Docker Desktop with WSL 2 backend |

## Rules

- `uv.lock` is the dependency authority; update it intentionally with `uv lock`.
- `.venv` belongs to the project and is never committed.
- Development PostgreSQL is the Compose `postgres` service on port 5432.
- The API reads `KJDS_DATABASE_URL`; real values belong in ignored `.env` or a secret manager.
- Production images run migrations before starting the API during the current single-instance phase.

## Common commands

```powershell
.\scripts\bootstrap.ps1
.\scripts\dev.ps1
uv run python -m alembic current
uv run python -m pytest
uv run ruff check .
docker compose down
```
