$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Web = Join-Path $Root "web"
Set-Location $Web
New-Item -ItemType Directory -Force (Join-Path $Root ".runtime") | Out-Null
$PID | Set-Content (Join-Path $Root ".runtime\web.pid")
$env:KJDS_API_URL = "http://127.0.0.1:8000"
npm run dev -- --hostname 127.0.0.1 --port 3000
