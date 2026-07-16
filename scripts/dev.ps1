$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

docker compose up -d postgres
$env:KJDS_DATABASE_URL = "postgresql+psycopg://hermes:hermes_dev@localhost:5432/hermes"
uv run python -m alembic upgrade head
uv run python -m uvicorn apps.control_plane.api:app --reload --host 127.0.0.1 --port 8000
