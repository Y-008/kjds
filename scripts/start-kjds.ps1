$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Test-LocalPort([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Get-Setting([string]$Name, [string]$Default) {
    $environmentValue = [Environment]::GetEnvironmentVariable($Name)
    if ($environmentValue) { return $environmentValue }
    $envFile = Join-Path $Root ".env"
    if (Test-Path $envFile) {
        $line = Get-Content $envFile | Where-Object { $_ -match "^$([regex]::Escape($Name))=" } | Select-Object -First 1
        if ($line) { return ($line -split "=", 2)[1].Trim() }
    }
    return $Default
}

function Get-ListeningProcess([int]$Port) {
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $connection) { return $null }
    return Get-CimInstance Win32_Process -Filter "ProcessId=$($connection.OwningProcess)"
}

function Test-ApiFingerprint {
    try {
        $version = Invoke-RestMethod "http://127.0.0.1:8000/version" -TimeoutSec 3
        return $version.service -eq "kjds-control-plane" -and $version.version -eq "0.3.0"
    } catch { return $false }
}

function Stop-StaleKjdsProcess([int]$Port, [string]$ExpectedMarker) {
    $process = Get-ListeningProcess $Port
    if (-not $process) { return }
    $normalizedRoot = $Root.ToLowerInvariant()
    $command = [string]$process.CommandLine
    if ($command.ToLowerInvariant().Contains($normalizedRoot) -and $command.ToLowerInvariant().Contains($ExpectedMarker)) {
        Stop-Process -Id $process.ProcessId -Force
        Start-Sleep -Milliseconds 800
        return
    }
    throw "Port $Port is occupied by another program (PID $($process.ProcessId)). KJDS did not stop it."
}

$databaseProvider = Get-Setting "KJDS_DATABASE_PROVIDER" "local-postgres"
$apiKey = Get-Setting "KJDS_API_KEY" ""
if (-not $apiKey -or $apiKey -like "replace-*") {
    throw "KJDS_API_KEY must be configured in .env before KJDS can start."
}
$env:KJDS_API_KEY = $apiKey
if ($databaseProvider -ne "supabase") {
    docker compose up -d postgres
}
uv run python -m alembic upgrade head

if (-not (Test-LocalPort 11434)) {
    $ollama = (Get-Command ollama -ErrorAction Stop).Source
    Start-Process $ollama -ArgumentList "serve" -WindowStyle Hidden
}

if (-not (Test-LocalPort 5678)) {
    docker compose -f "D:\AI\Stacks\n8n-local\docker-compose.yml" up -d --pull never
}

if (-not (Test-LocalPort 3002)) {
    docker compose -f "D:\AI\Stacks\firecrawl\docker-compose.yaml" up -d
}

if (-not (Test-LocalPort 8189)) {
    Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "D:\AI\Apps\OpenClaw\workspace-chief\scripts\start-comfyui-latest.ps1" -WindowStyle Hidden
}

if ((Test-LocalPort 8000) -and -not (Test-ApiFingerprint)) {
    Stop-StaleKjdsProcess 8000 "uvicorn"
}
if (-not (Test-ApiFingerprint)) {
    Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "run-api.ps1") -WindowStyle Hidden
}

if (-not (Test-LocalPort 3000)) {
    Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "run-web.ps1") -WindowStyle Hidden
}

$deadline = (Get-Date).AddSeconds(55)
do {
    try {
        $apiReady = Test-ApiFingerprint -and (Invoke-RestMethod "http://127.0.0.1:8000/health/ready" -TimeoutSec 3).status -eq "ok"
        $webReady = (Invoke-WebRequest "http://127.0.0.1:3000" -TimeoutSec 3 -UseBasicParsing).StatusCode -eq 200
    } catch {
        $apiReady = $false
        $webReady = $false
    }
    $ready = $webReady -and $apiReady -and (Test-LocalPort 8189) -and (Test-LocalPort 5678) -and (Test-LocalPort 3002) -and (Test-LocalPort 11434)
    if ($ready) { break }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)

if (-not $ready) {
    throw "KJDS is still starting. Please run this script again after one minute."
}

Start-Process "http://127.0.0.1:3000"
Write-Output "KJDS is ready: http://127.0.0.1:3000"
