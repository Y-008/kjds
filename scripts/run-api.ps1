$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
New-Item -ItemType Directory -Force (Join-Path $Root ".runtime") | Out-Null
$PID | Set-Content (Join-Path $Root ".runtime\api.pid")
uv run python -m uvicorn apps.control_plane.api:app --host 127.0.0.1 --port 8000
