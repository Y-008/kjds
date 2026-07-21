$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
New-Item -ItemType Directory -Force (Join-Path $Root ".runtime") | Out-Null
$PID | Set-Content (Join-Path $Root ".runtime\api.pid")

# Direct launches must receive the same dedicated identity map as Compose.
# Keep the value in the process environment only; never echo it to logs.
if (-not $env:KJDS_API_KEYS_JSON) {
    $envFile = Join-Path $Root ".env"
    if (Test-Path -LiteralPath $envFile) {
        $line = Get-Content -LiteralPath $envFile | Where-Object {
            $_ -match "^KJDS_API_KEYS_JSON="
        } | Select-Object -First 1
        if ($line) { $env:KJDS_API_KEYS_JSON = ($line -split "=", 2)[1].Trim() }
    }
}
uv run python -m uvicorn apps.control_plane.api:app --host 127.0.0.1 --port 8000
