#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
uv python pin 3.12
uv sync --extra dev --frozen
docker compose up -d postgres

for _ in $(seq 1 45); do
  if docker compose exec -T postgres pg_isready -U hermes -d hermes >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

docker compose exec -T postgres pg_isready -U hermes -d hermes
export KJDS_DATABASE_URL="postgresql+psycopg://hermes:hermes_dev@localhost:5432/hermes"
uv run python -m alembic upgrade head
uv run ruff check .
uv run python -m pytest
echo "Hermes bootstrap complete."
