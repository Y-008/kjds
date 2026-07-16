$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Runtime = Join-Path $Root ".runtime"
$Web = Join-Path $Root "web"
$WebSmoke = Join-Path $Runtime ("web-g1-" + [guid]::NewGuid().ToString("N"))
$DatabaseName = "kjds_g1_smoke"
$ApiPort = 8010
$WebPort = 3010
$ApiProcess = $null
$WebProcess = $null
$PostgresContainer = $null

New-Item -ItemType Directory -Force $Runtime | Out-Null
Set-Location $Root

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE"
    }
}

function Wait-Until {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Condition,
        [Parameter(Mandatory = $true)][string]$Description,
        [int]$TimeoutSeconds = 45
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (& $Condition) { return }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    throw "Timed out waiting for $Description"
}

function Test-HttpOk {
    param([string]$Url)
    try {
        return (Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200
    } catch {
        return $false
    }
}

function Stop-OwnedProcess {
    param($Process)
    if ($null -ne $Process -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        $Process.WaitForExit(5000) | Out-Null
    }
}

function Stop-SmokeProcesses {
    $markers = @("--port $ApiPort", "--port $WebPort", $WebSmoke)
    $processes = Get-CimInstance Win32_Process | Where-Object {
        $commandLine = [string]$_.CommandLine
        $markers | Where-Object { $commandLine.Contains($_) }
    }
    foreach ($process in $processes) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 500
}

$startedAt = (Get-Date).ToUniversalTime()
$result = [ordered]@{
    gate = "G-1"
    status = "FAIL"
    started_at = $startedAt.ToString("o")
    finished_at = $null
    git_commit = $null
    migration = $null
    migration_replay = $false
    lint = $false
    tests = $false
    web_build = $false
    api_health = $false
    api_database_write = $false
    web_health = $false
    cleanup_processes = $false
    cleanup_database = $false
    cleanup_files = $false
    report = (Join-Path $Runtime "G1_VERIFICATION.json")
}

try {
    Write-Output "[G-1] Checking required commands and Git revision"
    foreach ($command in @("docker", "uv", "npm.cmd")) {
        if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
            throw "Required command is unavailable: $command"
        }
    }

    Invoke-External -Command git -Arguments @("rev-parse", "--verify", "HEAD")
    $result.git_commit = (git rev-parse HEAD).Trim()

    Write-Output "[G-1] Starting PostgreSQL"
    Invoke-External -Command docker -Arguments @("compose", "up", "-d", "postgres")
    $PostgresContainer = (docker compose ps -q postgres).Trim()
    if (-not $PostgresContainer) { throw "PostgreSQL container was not created" }
    Wait-Until -Description "PostgreSQL health" -Condition {
        (docker inspect --format "{{.State.Health.Status}}" $PostgresContainer 2>$null).Trim() -eq "healthy"
    }

    Write-Output "[G-1] Replaying migrations in disposable database"
    Invoke-External -Command docker -Arguments @("exec", $PostgresContainer, "dropdb", "--if-exists", "-U", "hermes", $DatabaseName)
    Invoke-External -Command docker -Arguments @("exec", $PostgresContainer, "createdb", "-U", "hermes", $DatabaseName)

    $env:KJDS_DATABASE_URL = "postgresql+psycopg://hermes:hermes_dev@127.0.0.1:5432/$DatabaseName"
    $env:KJDS_DATABASE_PROVIDER = "local-postgres"
    $env:KJDS_REPOSITORY = "postgres"
    $env:KJDS_SHADOW_MODE = "true"

    Invoke-External -Command uv -Arguments @("run", "python", "-m", "alembic", "upgrade", "head")
    $current = (uv run python -m alembic current).Trim()
    if ($LASTEXITCODE -ne 0 -or $current -notmatch "20260713_0003.*head") {
        throw "Unexpected migration head: $current"
    }
    $result.migration = "20260713_0003"

    Invoke-External -Command uv -Arguments @("run", "python", "-m", "alembic", "downgrade", "20260712_0002")
    $downgraded = (uv run python -m alembic current).Trim()
    if ($LASTEXITCODE -ne 0 -or $downgraded -notmatch "20260712_0002") {
        throw "Migration downgrade verification failed: $downgraded"
    }
    Invoke-External -Command uv -Arguments @("run", "python", "-m", "alembic", "upgrade", "head")
    $result.migration_replay = $true

    Write-Output "[G-1] Running Python quality gates"
    Invoke-External -Command uv -Arguments @("run", "ruff", "check", ".")
    $result.lint = $true
    Invoke-External -Command uv -Arguments @("run", "python", "-m", "pytest", "-q")
    $result.tests = $true

    Write-Output "[G-1] Building isolated web bundle"
    New-Item -ItemType Directory -Force $WebSmoke | Out-Null
    Copy-Item -LiteralPath (Join-Path $Web "app") -Destination $WebSmoke -Recurse
    foreach ($file in @("next-env.d.ts", "next.config.ts", "package.json", "package-lock.json", "tsconfig.json")) {
        Copy-Item -LiteralPath (Join-Path $Web $file) -Destination (Join-Path $WebSmoke $file)
    }
    New-Item -ItemType Junction -Path (Join-Path $WebSmoke "node_modules") -Target (Join-Path $Web "node_modules") | Out-Null
    Push-Location $WebSmoke
    try {
        Invoke-External -Command npm.cmd -Arguments @("run", "build", "--", "--webpack")
        $result.web_build = $true
    } finally {
        Pop-Location
    }

    Write-Output "[G-1] Starting disposable API on port $ApiPort"
    $ApiProcess = Start-Process -FilePath (Get-Command uv).Source `
        -ArgumentList @("run", "python", "-m", "uvicorn", "apps.control_plane.api:app", "--host", "127.0.0.1", "--port", "$ApiPort") `
        -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $Runtime "g1-api.stdout.log") `
        -RedirectStandardError (Join-Path $Runtime "g1-api.stderr.log")
    Wait-Until -Description "G-1 API" -Condition { Test-HttpOk "http://127.0.0.1:$ApiPort/health/ready" }

    $health = Invoke-RestMethod "http://127.0.0.1:$ApiPort/health/ready" -TimeoutSec 5
    if ($health.status -ne "ok" -or $health.database.status -ne "ok") {
        throw "API health did not confirm PostgreSQL readiness"
    }
    $result.api_health = $true

    $sku = "G1-SMOKE-" + (Get-Date -Format "yyyyMMddHHmmss")
    $body = @{ sku = $sku; name = "Disposable G-1 smoke product" } | ConvertTo-Json
    $product = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/products" -Method Post -ContentType "application/json" -Body $body
    $readiness = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/products/$($product.id)/readiness"
    $events = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/events"
    if ($readiness.ready_for_validation -ne $false -or -not ($events | Where-Object aggregate_id -eq $product.id)) {
        throw "API write/read/event smoke failed"
    }
    $result.api_database_write = $true

    Write-Output "[G-1] Starting disposable web UI on port $WebPort"
    $env:KJDS_API_URL = "http://127.0.0.1:$ApiPort"
    $WebProcess = Start-Process -FilePath (Get-Command npm.cmd).Source `
        -ArgumentList @("run", "dev", "--", "--webpack", "--hostname", "127.0.0.1", "--port", "$WebPort") `
        -WorkingDirectory $WebSmoke -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $Runtime "g1-web.stdout.log") `
        -RedirectStandardError (Join-Path $Runtime "g1-web.stderr.log")
    Wait-Until -Description "G-1 web UI" -Condition { Test-HttpOk "http://127.0.0.1:$WebPort" }
    $webResponse = Invoke-WebRequest "http://127.0.0.1:$WebPort" -UseBasicParsing -TimeoutSec 5
    if ($webResponse.Content -notmatch "KJDS") { throw "Web UI response did not contain the KJDS fingerprint" }
    $result.web_health = $true

    $result.status = "PASS"
} catch {
    $result.error = $_.Exception.Message
    throw
} finally {
    Stop-OwnedProcess $WebProcess
    Stop-OwnedProcess $ApiProcess
    Stop-SmokeProcesses
    $remainingListeners = Get-NetTCPConnection -LocalPort $ApiPort, $WebPort -State Listen -ErrorAction SilentlyContinue
    $result.cleanup_processes = $null -eq $remainingListeners
    if ($PostgresContainer) {
        docker exec $PostgresContainer dropdb --if-exists --force -U hermes $DatabaseName 2>$null | Out-Null
        $remainingDatabase = docker exec $PostgresContainer psql -U hermes -d postgres -Atc "SELECT datname FROM pg_database WHERE datname='$DatabaseName';" 2>$null
        $result.cleanup_database = $LASTEXITCODE -eq 0 -and -not $remainingDatabase
    }
    if (Test-Path $WebSmoke) {
        $resolvedRuntime = [IO.Path]::GetFullPath($Runtime).TrimEnd("\") + "\"
        $resolvedSmoke = [IO.Path]::GetFullPath($WebSmoke)
        if ($resolvedSmoke.StartsWith($resolvedRuntime, [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath (Join-Path $WebSmoke "node_modules") -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $WebSmoke -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    $result.cleanup_files = -not (Test-Path $WebSmoke)
    if ($result.status -eq "PASS" -and -not ($result.cleanup_processes -and $result.cleanup_database -and $result.cleanup_files)) {
        $result.status = "FAIL"
        $result.cleanup_error = "Disposable verification resources were not fully removed"
    }
    $result.finished_at = (Get-Date).ToUniversalTime().ToString("o")
    $result | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $Runtime "G1_VERIFICATION.json")
    Write-Output ($result | ConvertTo-Json -Depth 5)
}
