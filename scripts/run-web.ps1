$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Web = Join-Path $Root "web"

function Get-Setting([string]$Name) {
    $environmentValue = [Environment]::GetEnvironmentVariable($Name)
    if ($environmentValue) { return $environmentValue }
    $envFile = Join-Path $Root ".env"
    if (Test-Path $envFile) {
        $line = Get-Content $envFile | Where-Object { $_ -match "^$([regex]::Escape($Name))=" } | Select-Object -First 1
        if ($line) { return ($line -split "=", 2)[1].Trim() }
    }
    return $null
}

$apiKey = Get-Setting "KJDS_API_KEY"
if (-not $apiKey -or $apiKey -like "replace-*") {
    throw "KJDS_API_KEY must be configured in the root .env before starting the web UI."
}

Set-Location $Web
New-Item -ItemType Directory -Force (Join-Path $Root ".runtime") | Out-Null
$PID | Set-Content (Join-Path $Root ".runtime\web.pid")
$env:KJDS_API_URL = "http://127.0.0.1:8000"
$env:KJDS_API_KEY = $apiKey
npm run dev -- --hostname 127.0.0.1 --port 3000
