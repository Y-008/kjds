$ErrorActionPreference = "Stop"

if (-not $env:OZON_CLIENT_ID -or -not $env:OZON_API_KEY) {
    throw "OZON_CLIENT_ID and OZON_API_KEY must be set only in the isolated worker environment."
}
if (-not $env:KJDS_EXECUTOR_API_KEY) {
    throw "KJDS_EXECUTOR_API_KEY is required for the dedicated executor identity."
}

uv run python -m apps.control_plane.ozon_worker @args
