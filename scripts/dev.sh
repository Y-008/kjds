#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
docker compose up -d postgres
export KJDS_DATABASE_URL="postgresql+psycopg://hermes:hermes_dev@localhost:5432/hermes"
uv run alembic upgrade head
exec uv run uvicorn apps.control_plane.api:app --reload --host 127.0.0.1 --port 8000
