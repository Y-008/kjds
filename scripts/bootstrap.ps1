$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

uv python pin 3.12
uv sync --extra dev --frozen
docker compose up -d postgres

$deadline = (Get-Date).AddSeconds(90)
do {
    docker compose exec -T postgres pg_isready -U hermes -d hermes *> $null
    $healthy = $LASTEXITCODE -eq 0
    if ($healthy) { break }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)

if (-not $healthy) { throw "PostgreSQL did not become healthy within 90 seconds." }

$env:KJDS_DATABASE_URL = "postgresql+psycopg://hermes:hermes_dev@localhost:5432/hermes"
uv run alembic upgrade head
uv run ruff check .
uv run pytest
Write-Output "Hermes bootstrap complete."
