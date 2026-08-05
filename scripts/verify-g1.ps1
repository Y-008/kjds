param([switch]$UseExistingPostgres)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Runtime = Join-Path $Root ".runtime"
$Web = Join-Path $Root "web"
$WebSmoke = Join-Path $Runtime ("web-g1-" + [guid]::NewGuid().ToString("N"))
$PytestTemp = Join-Path $Runtime ("pytest-g1-" + [guid]::NewGuid().ToString("N"))
$BackupSmokeDirectory = Join-Path $Runtime ("backup-g1-" + [guid]::NewGuid().ToString("N"))
$ReleaseEvidenceDirectory = Join-Path $Runtime ("release-g1-" + [guid]::NewGuid().ToString("N"))
$DatabaseName = "kjds_g1_smoke"
$RestoreDatabaseName = "kjds_g1_restore"
$ApiPort = 8010
$WebPort = 3010
$EvidenceSmokeFile = Join-Path $Runtime ("g1-evidence-" + [guid]::NewGuid().ToString("N") + ".txt")
$ApiProcess = $null
$WebProcess = $null
$PostgresContainer = $null
$WebContainer = $null
$Python = if ($env:KJDS_G1_PYTHON) {
    $env:KJDS_G1_PYTHON
} else {
    Join-Path $Root ".venv\Scripts\python.exe"
}
$MigrationDatabaseUrl = "postgresql+psycopg://hermes:hermes_dev@127.0.0.1:5432/$DatabaseName"
$CoverageIssuerPassword = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
$RuntimeDatabasePassword = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
$RunToken = ([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N"))
$DatabaseLeaseAcquired = $false
$DatabaseLeaseEverAcquired = $false
$CoverageIssuerDatabaseUrl = "postgresql+psycopg://kjds_gdc_issuance_runtime:$CoverageIssuerPassword@127.0.0.1:5432/$DatabaseName"
$RuntimeDatabaseUrl = "postgresql+psycopg://kjds_g1_runtime:$RuntimeDatabasePassword@127.0.0.1:5432/$DatabaseName"

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

function Get-HttpStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [string]$Method = "Get",
        [hashtable]$Headers = @{},
        [string]$ContentType,
        [string]$Body
    )

    $parameters = @{
        Uri = $Url
        Method = $Method
        Headers = $Headers
        UseBasicParsing = $true
    }
    if ($PSBoundParameters.ContainsKey("ContentType")) { $parameters.ContentType = $ContentType }
    if ($PSBoundParameters.ContainsKey("Body")) { $parameters.Body = $Body }
    try {
        return [int](Invoke-WebRequest @parameters).StatusCode
    } catch {
        if ($null -ne $_.Exception.Response -and $null -ne $_.Exception.Response.StatusCode) {
            return [int]$_.Exception.Response.StatusCode
        }
        throw
    }
}

function Stop-OwnedProcess {
    param($Process)
    if ($null -ne $Process -and -not $Process.HasExited) {
        try {
            $Process.Kill($true)
        } catch {
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        }
        $Process.WaitForExit(5000) | Out-Null
    }
}

function Stop-OwnedListener {
    param(
        $Process,
        [int]$Port
    )
    if ($null -eq $Process) { return }
    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

function Stop-SmokeProcesses {
    $markers = @("--port $ApiPort", "--port $WebPort", "start -p $WebPort", $WebSmoke)
    try {
        $processes = Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            $commandLine = [string]$_.CommandLine
            $markers | Where-Object { $commandLine.Contains($_) }
        }
        foreach ($process in $processes) {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Milliseconds 500
    } catch {
        # Owned child processes are stopped separately. Some managed runners
        # intentionally deny global process enumeration.
    }
}

function Invoke-CleanupStep {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )

    try {
        & $Action | Out-Null
    } catch {
        return "Cleanup step '${Name}' failed: $($_.Exception.Message)"
    }
}

function Remove-OwnedPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$RuntimeRoot,
        [switch]$Recurse,
        [int]$Attempts = 8
    )

    if (-not (Test-Path -LiteralPath $Path)) { return }
    try {
        $resolvedRuntime = [IO.Path]::GetFullPath($RuntimeRoot).TrimEnd("\", "/") + [IO.Path]::DirectorySeparatorChar
        $resolvedPath = [IO.Path]::GetFullPath($Path)
        if (-not $resolvedPath.StartsWith($resolvedRuntime, [StringComparison]::OrdinalIgnoreCase)) {
            return "Refused to remove path outside runtime directory: $resolvedPath"
        }
    } catch {
        return "Unable to validate disposable path ${Path}: $($_.Exception.Message)"
    }

    if ($Recurse) {
        try {
            Get-ChildItem `
                -LiteralPath $resolvedPath `
                -Recurse `
                -Force `
                -File | Where-Object {
                    $_.IsReadOnly
                } | ForEach-Object {
                    $_.IsReadOnly = $false
                }
        } catch {
            return "Unable to clear read-only files under ${resolvedPath}: $($_.Exception.Message)"
        }
    }

    $lastError = $null
    for ($attempt = 1; $attempt -le $Attempts -and (Test-Path -LiteralPath $Path); $attempt++) {
        try {
            if (Test-Path -LiteralPath $Path -PathType Container) {
                [IO.Directory]::Delete($resolvedPath, $Recurse.IsPresent)
            } else {
                [IO.File]::Delete($resolvedPath)
            }
        } catch {
            $lastError = $_.Exception.Message
            if ($attempt -lt $Attempts) { Start-Sleep -Milliseconds 250 }
        }
    }
    if (Test-Path -LiteralPath $Path) {
        return "Cleanup failed for ${resolvedPath} after $Attempts attempts: $lastError"
    }
}

function Write-G1Report {
    param(
        [Parameter(Mandatory = $true)]$Result,
        [Parameter(Mandatory = $true)][string]$Path
    )

    try {
        $reportJson = $Result | ConvertTo-Json -Depth 5
    } catch {
        $Result.status = "FAIL"
        $Result.report_error =
            "Unable to serialize complete G-1 report: $($_.Exception.Message)"
        $reportJson = [ordered]@{
            gate = "G-1"
            status = "FAIL"
            started_at = $Result.started_at
            finished_at = (Get-Date).ToUniversalTime().ToString("o")
            git_commit = $Result.git_commit
            error = $Result.report_error
            verification_error = $Result.error
            cleanup_processes = [bool]$Result.cleanup_processes
            cleanup_database = [bool]$Result.cleanup_database
            cleanup_files = [bool]$Result.cleanup_files
        } | ConvertTo-Json -Depth 3
    }

    $reportTemporaryPath = "$Path.tmp-$([guid]::NewGuid().ToString('N'))"
    try {
        $reportJson | Set-Content `
            -LiteralPath $reportTemporaryPath `
            -Encoding UTF8 `
            -NoNewline
        Move-Item `
            -LiteralPath $reportTemporaryPath `
            -Destination $Path `
            -Force
    } catch {
        Remove-Item `
            -LiteralPath $reportTemporaryPath `
            -Force `
            -ErrorAction SilentlyContinue
        $Result.status = "FAIL"
        $Result.report_error =
            "Unable to write G-1 report: $($_.Exception.Message)"
        $reportJson = [ordered]@{
            gate = "G-1"
            status = "FAIL"
            git_commit = $Result.git_commit
            error = $Result.report_error
        } | ConvertTo-Json -Depth 2
    }
    [Console]::Out.WriteLine($reportJson)
    return $null -eq $Result.report_error
}

function Complete-G1Verification {
    param(
        [Parameter(Mandatory = $true)]$Result,
        [Parameter(Mandatory = $true)][object[]]$CleanupSteps,
        [Parameter(Mandatory = $true)][string]$ReportPath
    )

    foreach ($step in $CleanupSteps) {
        $Result.cleanup_file_errors += @(
            Invoke-CleanupStep -Name $step.Name -Action $step.Action
        )
    }

    if (
        $Result.cleanup_file_errors.Count -gt 0 -or
        -not (
            $Result.cleanup_processes -and
            $Result.cleanup_database -and
            $Result.cleanup_files
        )
    ) {
        $Result.status = "FAIL"
        $Result.cleanup_error =
            "Disposable verification resources were not fully removed"
    }

    $Result.finished_at = (Get-Date).ToUniversalTime().ToString("o")
    $reportWritten = Write-G1Report -Result $Result -Path $ReportPath
    return [ordered]@{
        failed = $Result.status -ne "PASS" -or -not $reportWritten
        report_written = [bool]$reportWritten
    }
}

$startedAt = (Get-Date).ToUniversalTime()
$result = [ordered]@{
    gate = "G-1"
    status = "FAIL"
    started_at = $startedAt.ToString("o")
    finished_at = $null
    git_commit = $null
    database_control_mode = $(if ($UseExistingPostgres) { "existing-postgres" } else { "docker-compose" })
    migration = $null
    migration_replay = $false
    transactional_outbox = $false
    sourcing_numeric_integrity = $false
    finance_numeric_integrity = $false
    decision_experiment_numeric_integrity = $false
    policy_capability_numeric_integrity = $false
    core_numeric_integrity = $false
    domain_contracts = $false
    backup_restore = $false
    backup_restore_sha256 = $null
    backup_restore_elapsed_seconds = $null
    backup_restore_counts = $null
    runtime_identity_config = $false
    secret_scan = $false
    startup_package_contract = $false
    lint = $false
    tests = $false
    web_tests = $false
    web_build = $false
    container_import = $false
    release_provenance = $false
    release_software_sbom = $false
    release_ai_bom = $false
    release_postgres_subject = $false
    release_deployment_policy = $false
    release_slsa_build_level = $null
    release_api_image_sha256 = $null
    release_postgres_image_sha256 = $null
    web_container_health = $false
    api_health = $false
    api_auth = $false
    loop_engineering_registry = $false
    loop_engineering_validation = $false
    kill_switch = $false
    api_database_write = $false
    evidence_ledger = $false
    evidence_integrity_monitor = $false
    evidence_integrity_health_loop = $false
    evidence_health_task_contract = $false
    ozon_worker_contract_test = $false
    ozon_credential_isolation = $false
    ozon_pilot_preflight = $false
    ozon_worker_execution_intent = $false
    web_health = $false
    web_proxy_auth = $false
    cleanup_processes = $false
    cleanup_database = $false
    cleanup_files = $false
    cleanup_error = $null
    cleanup_file_errors = @()
    error = $null
    report_error = $null
    report = (Join-Path $Runtime ("G1_VERIFICATION-" + $RunToken + ".json"))
}

try {
    Write-Output "[G-1] Checking required commands and Git revision"
    if ($PSVersionTable.PSVersion.Major -lt 7) {
        throw "G-1 requires PowerShell 7 or newer because multipart smoke tests use -Form"
    }
    $requiredCommands = @("uv", "npm.cmd", "docker")
    foreach ($command in $requiredCommands) {
        if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
            throw "Required command is unavailable: $command"
        }
    }

    Invoke-External -Command git -Arguments @("rev-parse", "--verify", "HEAD")
    $result.git_commit = (git rev-parse HEAD).Trim()

    $env:KJDS_DATABASE_URL = $MigrationDatabaseUrl
    $env:KJDS_G1_COVERAGE_ISSUER_PASSWORD = $CoverageIssuerPassword
    $env:KJDS_G1_RUNTIME_PASSWORD = $RuntimeDatabasePassword
    $env:KJDS_G1_RUN_TOKEN = $RunToken
    $env:KJDS_GLOBAL_DATA_COVERAGE_ISSUER_DATABASE_URL = $CoverageIssuerDatabaseUrl
    $env:KJDS_DATABASE_PROVIDER = "local-postgres"
    # The gate must not inherit a machine-level cache path that a managed
    # runner cannot access. This override is scoped to this process only.
    $env:UV_CACHE_DIR = Join-Path $Runtime "uv-cache"

    if ($UseExistingPostgres) {
        Write-Output "[G-1] Using reachable PostgreSQL without Docker control-plane access"
        Invoke-External -Command $Python -Arguments @("scripts/manage_g1_database.py", "acquire")
        $DatabaseLeaseAcquired = $true
        $DatabaseLeaseEverAcquired = $true
        $result.report = (Join-Path $Runtime "G1_VERIFICATION.json")
        Invoke-External -Command $Python -Arguments @("scripts/manage_g1_database.py", "recreate")
    } else {
        Write-Output "[G-1] Starting PostgreSQL"
        Invoke-External -Command docker -Arguments @("compose", "up", "-d", "postgres")
        $PostgresContainer = (docker compose ps -q postgres).Trim()
        if (-not $PostgresContainer) { throw "PostgreSQL container was not created" }
        Wait-Until -Description "PostgreSQL health" -Condition {
            (docker inspect --format "{{.State.Health.Status}}" $PostgresContainer 2>$null).Trim() -eq "healthy"
        }
        Invoke-External -Command $Python -Arguments @("scripts/manage_g1_database.py", "acquire")
        $DatabaseLeaseAcquired = $true
        $DatabaseLeaseEverAcquired = $true
        $result.report = (Join-Path $Runtime "G1_VERIFICATION.json")
        Invoke-External -Command $Python -Arguments @("scripts/manage_g1_database.py", "recreate")
    }
    Write-Output "[G-1] Replaying migrations in disposable database"
    $env:KJDS_REPOSITORY = "postgres"
    $env:KJDS_SHADOW_MODE = "true"
    $env:KJDS_LIMITED_EXECUTION_ENABLED = "true"
    $env:KJDS_CONTROL_PLANE_URL = "http://127.0.0.1:$ApiPort"
    $env:KJDS_API_KEY = "g1-smoke-" + [guid]::NewGuid().ToString("N")
    $MonitorApiKey = "g1-monitor-" + [guid]::NewGuid().ToString("N")
    $env:KJDS_API_ACTOR = "g1-verifier"
    $env:KJDS_API_ROLES = "operator"
    $ApiCredentials = @{}
    $ApiCredentials[$env:KJDS_API_KEY] = @{ actor = "g1-verifier"; roles = @("operator", "reviewer", "admin") }
    $ApiCredentials[$MonitorApiKey] = @{ actor = "g1-monitor-worker"; roles = @("monitor") }
    $OperatingSubjectApiKey = "g1-operating-subject-" + [guid]::NewGuid().ToString("N")
    $ApiCredentials[$OperatingSubjectApiKey] = @{
        actor = "g1-operating-subject"
        roles = @("operator")
    }
    $env:KJDS_API_KEYS_JSON = $ApiCredentials | ConvertTo-Json -Compress
    $env:KJDS_MONITOR_API_KEY = $MonitorApiKey

    Invoke-External -Command uv -Arguments @("run", "python", "-m", "alembic", "upgrade", "head")
    $headLines = @(
        uv run python -m alembic heads |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ }
    )
    if ($LASTEXITCODE -ne 0 -or $headLines.Count -ne 1 -or $headLines[0] -notmatch '^([^ ]+) \(head\)$') {
        throw "Expected one Alembic head, found: $($headLines -join ', ')"
    }
    $expectedHead = $Matches[1]
    $current = (uv run python -m alembic current).Trim()
    if ($LASTEXITCODE -ne 0 -or $current -notmatch "^$([regex]::Escape($expectedHead)) \(head\)$") {
        throw "Unexpected migration head: $current"
    }
    $result.migration = $expectedHead

    Invoke-External -Command uv -Arguments @("run", "python", "-m", "alembic", "downgrade", "20260717_0024")
    $downgraded = (uv run python -m alembic current).Trim()
    if ($LASTEXITCODE -ne 0 -or $downgraded -notmatch "20260717_0024") {
        throw "Migration downgrade verification failed: $downgraded"
    }
    Invoke-External -Command uv -Arguments @("run", "python", "-m", "alembic", "upgrade", "head")
    $result.migration_replay = $true
    Invoke-External -Command $Python -Arguments @("scripts/manage_g1_database.py", "grant-runtime")
    $env:KJDS_RUNTIME_DATABASE_URL = $RuntimeDatabaseUrl

    Write-Output "[G-1] Seeding the disposable operating Gate observation graph"
    Invoke-External -Command uv -Arguments @(
        "run",
        "python",
        "scripts/seed_g1_operating_gate.py"
    )

    Write-Output "[G-1] Verifying transactional outbox on PostgreSQL"
    Invoke-External -Command uv -Arguments @("run", "python", "scripts/verify_outbox_postgres.py")
    $result.transactional_outbox = $true

    Write-Output "[G-1] Verifying sourcing numeric integrity on PostgreSQL"
    Invoke-External -Command uv -Arguments @("run", "python", "scripts/verify_sourcing_integrity_postgres.py")
    $result.sourcing_numeric_integrity = $true

    Write-Output "[G-1] Verifying finance numeric integrity on PostgreSQL"
    Invoke-External -Command uv -Arguments @("run", "python", "scripts/verify_finance_integrity_postgres.py")
    $result.finance_numeric_integrity = $true

    Write-Output "[G-1] Verifying decision and experiment numeric integrity on PostgreSQL"
    Invoke-External -Command uv -Arguments @("run", "python", "scripts/verify_decision_experiment_integrity_postgres.py")
    $result.decision_experiment_numeric_integrity = $true

    Write-Output "[G-1] Verifying policy and capability numeric integrity on PostgreSQL"
    Invoke-External -Command uv -Arguments @("run", "python", "scripts/verify_policy_capability_integrity_postgres.py")
    $result.policy_capability_numeric_integrity = $true

    Write-Output "[G-1] Running Python quality gates"
    Invoke-External -Command uv -Arguments @("run", "python", "scripts/validate_startup_package.py")
    $result.startup_package_contract = $true
    Invoke-External -Command uv -Arguments @("run", "python", "scripts/verify_secrets.py")
    $result.secret_scan = $true
    Invoke-External -Command uv -Arguments @("run", "python", "-m", "apps.control_plane.security")
    $result.runtime_identity_config = $true

    Write-Output "[G-1] Verifying the default-safe Evidence health task management contract"
    $healthTaskPlan = (& (Join-Path $PSScriptRoot "manage-evidence-health-task.ps1") -Mode Plan | Out-String) |
        ConvertFrom-Json
    if (
        $healthTaskPlan.status -ne "planned_no_mutation" -or
        $healthTaskPlan.mutation_performed -ne $false -or
        $healthTaskPlan.control_plane_only -ne $true -or
        $healthTaskPlan.command_contains_secrets -ne $false -or
        $healthTaskPlan.required_consecutive_successes -ne 3
    ) {
        throw "Evidence health task plan violated the no-mutation deployment contract"
    }
    $result.evidence_health_task_contract = $true
    # Validate the current worktree, including newly added files.  A Git-index
    # only list can silently omit untracked modules and tests during a smoke
    # run, which would make the report weaker than the code it claims to gate.
    $pythonFiles = @(
        Get-ChildItem (Join-Path $Root "apps"), (Join-Path $Root "migrations"), `
            (Join-Path $Root "tests"), (Join-Path $Root "scripts") -Recurse -Filter "*.py" -File |
            Where-Object { $_.FullName -notmatch "\\(__pycache__|\.pytest_cache|\.venv|\.runtime)\\" } |
            ForEach-Object { $_.FullName.Substring($Root.Length + 1) }
    ) | Sort-Object -Unique
    Invoke-External -Command uv -Arguments (@("run", "ruff", "check") + $pythonFiles)
    $result.lint = $true
    $testFiles = @(
        Get-ChildItem (Join-Path $Root "tests") -Filter "test_*.py" -File |
            ForEach-Object { $_.FullName.Substring($Root.Length + 1) }
    ) | Sort-Object
    Invoke-External -Command uv -Arguments (@("run", "python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp=$PytestTemp") + $testFiles)
    $result.tests = $true
    $result.domain_contracts = $true
    $result.ozon_worker_contract_test = $true
    $result.ozon_credential_isolation = $true

    Write-Output "[G-1] Running web security tests"
    Invoke-External -Command npm.cmd -Arguments @("--prefix", $Web, "test")
    $result.web_tests = $true

    Write-Output "[G-1] Building isolated web bundle"
    New-Item -ItemType Directory -Force $WebSmoke | Out-Null
    Copy-Item -LiteralPath (Join-Path $Web "app") -Destination $WebSmoke -Recurse
    Copy-Item -LiteralPath (Join-Path $Web "features") -Destination $WebSmoke -Recurse
    Copy-Item -LiteralPath (Join-Path $Web "lib") -Destination $WebSmoke -Recurse
    foreach ($file in @("next-env.d.ts", "next.config.ts", "package.json", "package-lock.json", "tsconfig.json")) {
        Copy-Item -LiteralPath (Join-Path $Web $file) -Destination (Join-Path $WebSmoke $file)
    }
    New-Item -ItemType Junction -Path (Join-Path $WebSmoke "node_modules") -Target (Join-Path $Web "node_modules") | Out-Null
    Invoke-External -Command npm.cmd -Arguments @("--prefix", $WebSmoke, "run", "build", "--", "--webpack")
    $result.web_build = $true

    Write-Output "[G-1] Verifying production API image contains required runtime assets"
    $env:KJDS_BUILD_COMMIT = $result.git_commit
    $env:KJDS_MIGRATION_HEAD = $result.migration
    Invoke-External -Command docker -Arguments @("compose", "build", "api", "web", "ozon-read-worker")

    Write-Output "[G-1] Verifying signed release provenance, SBOM and AI-BOM"
    $releaseOutput = & uv run python scripts/verify_release_provenance.py g1 `
        --api-image "kjds-api:latest" `
        --postgres-image "postgres:17-alpine" `
        --source-commit $result.git_commit `
        --migration-head $result.migration `
        --output-dir $ReleaseEvidenceDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "Release provenance verification failed"
    }
    $release = ($releaseOutput | Select-Object -Last 1) | ConvertFrom-Json
    if (
        $release.status -ne "PASS" -or
        $release.cryptographic_verification -ne $true -or
        $release.subject_verification -ne $true -or
        $release.cyclonedx_schema_validation -ne $true -or
        $release.secret_free -ne $true -or
        $release.postgres_version -notmatch '^17\.(?:1[0-9]|[2-9][0-9])' -or
        $release.slsa_build_level -ne "L1" -or
        $release.deployment_policy_status -ne "not_for_deployment" -or
        $release.production_dependency_allowed -ne $false -or
        $release.business_truth_gate_promoted -ne $false -or
        $release.formal_fact_created -ne $false -or
        $release.external_write_allowed -ne $false -or
        $release.software_component_count -lt 1 -or
        $release.ai_contract_count -lt 4
    ) {
        throw "Release provenance controls violated the G1 contract"
    }
    $result.release_provenance = $true
    $result.release_software_sbom = $true
    $result.release_ai_bom = $true
    $result.release_postgres_subject = $true
    $result.release_deployment_policy = $true
    $result.release_slsa_build_level = $release.slsa_build_level
    $result.release_api_image_sha256 = $release.api_image_sha256
    $result.release_postgres_image_sha256 = $release.postgres_image_sha256

    Invoke-External -Command docker -Arguments @(
        "compose",
        "run",
        "--rm",
        "--no-deps",
        "api",
        "python",
        "-c",
        "import apps.control_plane.api; print('container import ok')"
    )
    $result.container_import = $true

    Write-Output "[G-1] Verifying Ozon Pilot remains offline until explicit execution"
    $preflightOutput = & docker compose run --rm --no-deps `
        -e KJDS_PILOT_READER_API_KEY=g1-pilot-reader `
        -e OZON_CLIENT_ID=g1-seller-client `
        -e OZON_API_KEY=g1-ozon-reader `
        -e OZON_API_URL=https://api-seller.ozon.ru `
        -e OZON_PRODUCT_ATTRIBUTES_PATH=/v4/product/info/attributes `
        ozon-read-worker python -m apps.control_plane.ozon_read_worker `
        --preflight --pilot-id G1-PILOT --offer-id G1-OFFER `
        --idempotency-key g1-ozon-preflight
    if ($LASTEXITCODE -ne 0) {
        throw "Ozon Pilot offline preflight failed"
    }
    $preflight = $preflightOutput | Select-Object -Last 1 | ConvertFrom-Json
    $preflightText = $preflightOutput -join "`n"
    if (
        $preflight.status -ne "ready_for_explicit_execution" -or
        $preflight.mode -ne "offline_preflight" -or
        $preflight.network_calls_performed -ne $false -or
        $preflight.contract_version -ne "ozon-product-read-v1" -or
        $preflight.target_count -ne 1 -or
        $preflight.explicit_execution_required -ne $true -or
        $preflightText.Contains("g1-pilot-reader") -or
        $preflightText.Contains("g1-seller-client") -or
        $preflightText.Contains("g1-ozon-reader") -or
        $preflightText.Contains("G1-OFFER")
    ) {
        throw "Ozon Pilot preflight safety contract failed"
    }
    $result.ozon_pilot_preflight = $true

    Write-Output "[G-1] Verifying Ozon Worker cannot bypass explicit execution intent"
    $missingModeOutput = & docker compose run --rm --no-deps `
        -e KJDS_PILOT_READER_API_KEY=g1-intent-pilot-reader `
        -e OZON_CLIENT_ID=g1-intent-seller-client `
        -e OZON_API_KEY=g1-intent-ozon-reader `
        ozon-read-worker python -m apps.control_plane.ozon_read_worker `
        --pilot-id G1-INTENT-PILOT --offer-id G1-INTENT-OFFER `
        --idempotency-key g1-intent-missing-mode 2>&1
    $missingModeExit = $LASTEXITCODE
    $missingModeText = $missingModeOutput -join "`n"
    if (
        $missingModeExit -eq 0 -or
        -not $missingModeText.Contains("one of the arguments --preflight --execute is required") -or
        $missingModeText.Contains("g1-intent-pilot-reader") -or
        $missingModeText.Contains("g1-intent-seller-client") -or
        $missingModeText.Contains("g1-intent-ozon-reader")
    ) {
        throw "Ozon Worker accepted missing execution intent or exposed credentials"
    }

    $unboundExecutionOutput = & docker compose run --rm --no-deps `
        -e KJDS_CONTROL_PLANE_URL=http://control.example.com `
        -e KJDS_PILOT_READER_API_KEY=g1-revalidate-pilot-reader `
        -e OZON_CLIENT_ID=g1-revalidate-seller-client `
        -e OZON_API_KEY=g1-revalidate-ozon-reader `
        ozon-read-worker python -m apps.control_plane.ozon_read_worker `
        --execute --pilot-id G1-REVALIDATE-PILOT --offer-id G1-REVALIDATE-OFFER `
        --idempotency-key g1-execution-revalidation 2>&1
    $unboundExecutionExit = $LASTEXITCODE
    $unboundExecutionText = $unboundExecutionOutput -join "`n"
    if (
        $unboundExecutionExit -eq 0 -or
        -not $unboundExecutionText.Contains("Managed channel credential resolver is not bound") -or
        -not $unboundExecutionText.Contains("environment-only credentials cannot authorize a worker") -or
        $unboundExecutionText.Contains("g1-revalidate-pilot-reader") -or
        $unboundExecutionText.Contains("g1-revalidate-seller-client") -or
        $unboundExecutionText.Contains("g1-revalidate-ozon-reader")
    ) {
        throw "Ozon Worker accepted environment-only credentials or exposed credential material"
    }

    $revalidationOutput = & docker compose run --rm --no-deps `
        -e KJDS_CONTROL_PLANE_URL=http://control.example.com `
        -e KJDS_PILOT_READER_API_KEY=g1-revalidate-pilot-reader `
        -e OZON_CLIENT_ID=g1-revalidate-seller-client `
        -e OZON_API_KEY=g1-revalidate-ozon-reader `
        ozon-read-worker python -m apps.control_plane.ozon_read_worker `
        --preflight --pilot-id G1-REVALIDATE-PILOT --offer-id G1-REVALIDATE-OFFER `
        --idempotency-key g1-execution-revalidation 2>&1
    $revalidationExit = $LASTEXITCODE
    $revalidationText = $revalidationOutput -join "`n"
    if (
        $revalidationExit -eq 0 -or
        -not $revalidationText.Contains("requires HTTPS") -or
        $revalidationText.Contains("g1-revalidate-pilot-reader") -or
        $revalidationText.Contains("g1-revalidate-seller-client") -or
        $revalidationText.Contains("g1-revalidate-ozon-reader")
    ) {
        throw "Ozon Worker skipped offline endpoint revalidation or exposed credentials"
    }
    $result.ozon_worker_execution_intent = $true

    Write-Output "[G-1] Verifying production Web image starts from its standalone bundle"
    $WebContainer = "kjds-g1-web-" + [guid]::NewGuid().ToString("N")
    Invoke-External -Command docker -Arguments @(
        "run",
        "--detach",
        "--name",
        $WebContainer,
        "--env",
        "KJDS_ENVIRONMENT=development",
        "--env",
        "KJDS_WEB_AUTH_MODE=legacy",
        "--env",
        "KJDS_API_KEY=$($env:KJDS_API_KEY)",
        "kjds-web"
    )
    Wait-Until -Description "production Web container health" -Condition {
        docker exec $WebContainer node -e "fetch('http://127.0.0.1:3000').then(async r=>{const t=await r.text();if(!r.ok||!t.includes('KJDS'))process.exit(1)}).catch(()=>process.exit(1))" 2>$null
        $LASTEXITCODE -eq 0
    }
    $result.web_container_health = $true

    Write-Output "[G-1] Starting disposable API on port $ApiPort"
    $ApiProcess = Start-Process -FilePath (Get-Command uv).Source `
        -ArgumentList @("run", "python", "-m", "uvicorn", "apps.control_plane.api:app", "--host", "127.0.0.1", "--port", "$ApiPort") `
        -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $Runtime "g1-api.stdout.log") `
        -RedirectStandardError (Join-Path $Runtime "g1-api.stderr.log")
    Wait-Until -Description "G-1 API" -Condition { Test-HttpOk "http://127.0.0.1:$ApiPort/health/ready" }

    $health = Invoke-RestMethod "http://127.0.0.1:$ApiPort/health/ready" -TimeoutSec 5
    if ($health.status -ne "ok" -or $health.database.status -ne "ok" -or -not $health.security.api_identity_configured) {
        throw "API health did not confirm PostgreSQL readiness"
    }
    $result.api_health = $true

    $sku = "G1-SMOKE-" + (Get-Date -Format "yyyyMMddHHmmss")
    $body = @{ sku = $sku; name = "Disposable G-1 smoke product" } | ConvertTo-Json
    $headers = @{ "X-KJDS-API-Key" = $env:KJDS_API_KEY }
    $monitorHeaders = @{ "X-KJDS-API-Key" = $MonitorApiKey }
    $unauthorized = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/products"
    $invalid = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/products" -Headers @{ "X-KJDS-API-Key" = "invalid" }
    $authorized = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/products" -Headers $headers
    if ($unauthorized -ne 401 -or $invalid -ne 403 -or $authorized -ne 200) {
        throw "API authentication smoke failed"
    }
    $result.api_auth = $true

    $loopRegistry = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/loop-engineering/registry" -Headers $headers
    $loopModuleIds = @($loopRegistry.modules | ForEach-Object { $_.id })
    if (
        $loopRegistry.registry_id -ne "KJDS-LOOP-001" -or
        $loopModuleIds.Count -ne 6 -or
        "automations" -notin $loopModuleIds -or
        "memory" -notin $loopModuleIds
    ) {
        throw "Loop Engineering registry smoke failed"
    }
    $result.loop_engineering_registry = $true

    $switchBody = @{ reason = "G-1 kill switch exercise" } | ConvertTo-Json
    $engaged = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/system/kill-switch/engage" -Method Post -Headers $headers -ContentType "application/json" -Body $switchBody
    $loopValidation = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/loop-engineering/validate" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        module = "automations"
        mode = "shadow"
        controls = @{
            idempotency_key = "g1-loop-smoke"
            timeout = 30
            retry_limit = 0
            kill_switch = $false
            run_id = "g1-loop-run"
            evidence_id = "g1-loop-evidence"
        }
    } | ConvertTo-Json -Depth 4)
    $blocked = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/products" -Method Post -Headers $headers -ContentType "application/json" -Body $body
    $released = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/system/kill-switch/release" -Method Post -Headers $headers -ContentType "application/json" -Body (@{ reason = "G-1 exercise completed" } | ConvertTo-Json)
    if (
        -not $engaged.engaged -or
        -not $loopValidation.allowed -or
        $loopValidation.status -ne "shadow_ready" -or
        $blocked -ne 423 -or
        $released.engaged
    ) {
        throw "Kill switch smoke failed"
    }
    $result.loop_engineering_validation = $true
    $result.kill_switch = $true

    Set-Content -LiteralPath $EvidenceSmokeFile -Value "G-1 immutable evidence" -NoNewline -Encoding UTF8
    $evidenceRecord = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/evidence" -Method Post -Headers $headers -Form @{
        file = Get-Item $EvidenceSmokeFile
        source = "g1_verification"
        source_ref = "g1://verification/evidence"
        grade = "A"
        effective_at = "2026-07-16T00:00:00+08:00"
        metadata_json = '{"purpose":"G-1"}'
    }
    $verification = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/evidence/$($evidenceRecord.id)/verify" -Headers $headers
    $lineage = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/evidence/$($evidenceRecord.id)/lineage" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        target_type = "verification"
        target_id = "g1-api-database-write"
        relationship = "supports"
    } | ConvertTo-Json)
    if (-not $verification.valid -or $lineage.to_id -ne "g1-api-database-write") {
        throw "Immutable evidence and lineage smoke failed"
    }
    $result.api_database_write = $true
    $result.evidence_ledger = $true

    # Detailed business workflows run in the Python suite above.  G-1 keeps
    # only the cross-process API, database, Evidence, Worker and recovery seam.
    Write-Output "[G-1] Verifying bounded Evidence integrity monitoring"
    $integrityScan = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/evidence/integrity-scan?limit=500&offset=0&as_of=2026-07-19T10%3A00%3A00%2B00%3A00" -Method Post -Headers $monitorHeaders
    if (
        $integrityScan.scanned -lt 1 -or
        $integrityScan.invalid -ne 0 -or
        -not $integrityScan.scan_evidence_id -or
        $integrityScan.automatic_repair -ne $false -or
        $integrityScan.automatic_delete -ne $false -or
        $integrityScan.automatic_kill_switch_release -ne $false
    ) {
        throw "Evidence integrity monitor smoke failed"
    }
    $result.evidence_integrity_monitor = $true

    Write-Output "[G-1] Verifying the 24x7 health loop with its dedicated monitor identity"
    $healthLoop = (& (Join-Path $PSScriptRoot "run-24x7-health.ps1") -ControlPlaneOnly | Out-String) | ConvertFrom-Json
    if (
        -not $healthLoop.control_plane.ok -or
        -not $healthLoop.operations_readiness.ok -or
        -not $healthLoop.evidence_integrity.ok -or
        -not $healthLoop.agent_gate_observation.ok -or
        -not $healthLoop.evidence_integrity.completed -or
        $healthLoop.evidence_integrity.pages -lt 1 -or
        $healthLoop.evidence_integrity.invalid -ne 0
    ) {
        throw (
            "24x7 Evidence integrity health-loop smoke failed: " +
            "control_plane=$($healthLoop.control_plane.ok) " +
            "readiness=$($healthLoop.operations_readiness.ok) " +
            "integrity=$($healthLoop.evidence_integrity.ok) " +
            "agent_gate=$($healthLoop.agent_gate_observation.ok) " +
            "completed=$($healthLoop.evidence_integrity.completed) " +
            "pages=$($healthLoop.evidence_integrity.pages) " +
            "invalid=$($healthLoop.evidence_integrity.invalid)"
        )
    }
    $result.evidence_integrity_health_loop = $true

    Write-Output "[G-1] Verifying legacy core numeric integrity on PostgreSQL"
    Invoke-External -Command uv -Arguments @("run", "python", "scripts/verify_core_numeric_integrity_postgres.py")
    $result.core_numeric_integrity = $true

    if (-not $UseExistingPostgres) {
        Write-Output "[G-1] Verifying backup and isolated restore at current migration head"
        $backup = (& (Join-Path $PSScriptRoot "backup-postgres.ps1") `
            -OutputDirectory $BackupSmokeDirectory -Database $DatabaseName | Out-String) | ConvertFrom-Json
        & (Join-Path $PSScriptRoot "restore-postgres.ps1") `
            -BackupPath $backup.archive -TargetDatabase $RestoreDatabaseName | Out-Null
        $restore = Get-Content -LiteralPath (Join-Path $Runtime "RESTORE_VERIFICATION.json") -Raw | ConvertFrom-Json
        $countSql = "SELECT concat_ws('|',(SELECT count(*) FROM products),(SELECT count(*) FROM orders),(SELECT count(*) FROM evidence_records),(SELECT count(*) FROM read_only_pilot_runs));"
        $sourceCounts = (docker exec $PostgresContainer psql -U hermes -d $DatabaseName -Atc $countSql).Trim()
        $restoredCounts = (docker exec $PostgresContainer psql -U hermes -d $RestoreDatabaseName -Atc $countSql).Trim()
        if (
            $restore.status -ne "PASS" -or
            $restore.alembic_head -ne $result.migration -or
            -not $sourceCounts -or
            $sourceCounts -ne $restoredCounts
        ) {
            throw "Backup restore smoke failed: source=$sourceCounts restored=$restoredCounts head=$($restore.alembic_head)"
        }
        $countValues = $sourceCounts.Split("|")
        $result.backup_restore = $true
        $result.backup_restore_sha256 = $restore.sha256
        $result.backup_restore_elapsed_seconds = $restore.elapsed_seconds
        $result.backup_restore_counts = [ordered]@{
            products = [int]$countValues[0]
            orders = [int]$countValues[1]
            evidence_records = [int]$countValues[2]
            read_only_pilot_runs = [int]$countValues[3]
        }
    }

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
    $proxyResponse = Invoke-WebRequest "http://127.0.0.1:$WebPort/backend/v1/products" -UseBasicParsing -TimeoutSec 5
    if ($proxyResponse.StatusCode -ne 200) { throw "Web server-side API proxy authentication failed" }
    $result.web_proxy_auth = $true

    $result.status = "PASS"
} catch {
    $result.error = $_.Exception.Message
    throw
} finally {
    $nodeModulesJunction = Join-Path $WebSmoke "node_modules"
    $cleanupSteps = @(
        @{
            Name = "web container removal"
            Action = {
                if ($WebContainer) {
                    Invoke-External -Command docker -Arguments @(
                        "rm", "--force", $WebContainer
                    ) | Out-Null
                }
            }
        },
        @{
            Name = "web container verification"
            Action = {
                if ($WebContainer) {
                    $remainingWebContainer = docker ps -a `
                        --filter "name=^/$WebContainer$" -q 2>$null
                    if ($LASTEXITCODE -ne 0) {
                        throw "docker ps failed with exit code $LASTEXITCODE"
                    }
                    if ($remainingWebContainer) {
                        throw "Web container remains after cleanup"
                    }
                }
            }
        },
        @{
            Name = "web process"
            Action = { Stop-OwnedProcess $WebProcess }
        },
        @{
            Name = "API process"
            Action = { Stop-OwnedProcess $ApiProcess }
        },
        @{
            Name = "web listener"
            Action = { Stop-OwnedListener $WebProcess $WebPort }
        },
        @{
            Name = "API listener"
            Action = { Stop-OwnedListener $ApiProcess $ApiPort }
        },
        @{
            Name = "smoke processes"
            Action = {
                if ($DatabaseLeaseEverAcquired) { Stop-SmokeProcesses }
            }
        },
        @{
            Name = "process verification"
            Action = {
                if (-not $DatabaseLeaseEverAcquired) {
                    $result.cleanup_processes = $true
                    return
                }
                $remainingListeners = Get-NetTCPConnection `
                    -LocalPort $ApiPort, $WebPort `
                    -State Listen `
                    -ErrorAction SilentlyContinue
                $result.cleanup_processes = $null -eq $remainingListeners
                if (-not $result.cleanup_processes) {
                    throw "Ports $ApiPort or $WebPort still have listeners"
                }
            }
        },
        @{
            Name = "primary database"
            Action = {
                if ($DatabaseLeaseAcquired) {
                    $env:KJDS_DATABASE_URL = $MigrationDatabaseUrl
                    Invoke-External -Command $Python -Arguments @(
                        "scripts/manage_g1_database.py", "drop"
                    ) | Out-Null
                    $script:DatabaseLeaseAcquired = $false
                    $result.cleanup_database = $true
                }
            }
        },
        @{
            Name = "restore database"
            Action = {
                if ($DatabaseLeaseEverAcquired -and $PostgresContainer) {
                    Invoke-External -Command docker -Arguments @(
                        "exec", $PostgresContainer, "dropdb", "--if-exists",
                        "--force", "-U", "hermes", $RestoreDatabaseName
                    ) | Out-Null
                }
            }
        },
        @{
            Name = "database verification"
            Action = {
                if (-not $DatabaseLeaseEverAcquired) {
                    $result.cleanup_database = $true
                }
                if (-not $result.cleanup_database) {
                    throw "Owned disposable database cleanup was not confirmed"
                }
            }
        },
        @{
            Name = "coverage issuer credential environment"
            Action = {
                Remove-Item Env:KJDS_GLOBAL_DATA_COVERAGE_ISSUER_DATABASE_URL -ErrorAction SilentlyContinue
                Remove-Item Env:KJDS_RUNTIME_DATABASE_URL -ErrorAction SilentlyContinue
                Remove-Item Env:KJDS_G1_COVERAGE_ISSUER_PASSWORD -ErrorAction SilentlyContinue
                Remove-Item Env:KJDS_G1_RUNTIME_PASSWORD -ErrorAction SilentlyContinue
                Remove-Item Env:KJDS_G1_RUN_TOKEN -ErrorAction SilentlyContinue
            }
        },
        @{
            Name = "web node_modules junction"
            Action = {
                $errorMessage = Remove-OwnedPath `
                    -Path $nodeModulesJunction `
                    -RuntimeRoot $Runtime
                if ($errorMessage) { throw $errorMessage }
            }
        },
        @{
            Name = "web smoke directory"
            Action = {
                $errorMessage = Remove-OwnedPath `
                    -Path $WebSmoke `
                    -RuntimeRoot $Runtime `
                    -Recurse
                if ($errorMessage) { throw $errorMessage }
            }
        },
        @{
            Name = "pytest temporary directory"
            Action = {
                $errorMessage = Remove-OwnedPath `
                    -Path $PytestTemp `
                    -RuntimeRoot $Runtime `
                    -Recurse
                if ($errorMessage) { throw $errorMessage }
            }
        },
        @{
            Name = "backup smoke directory"
            Action = {
                $errorMessage = Remove-OwnedPath `
                    -Path $BackupSmokeDirectory `
                    -RuntimeRoot $Runtime `
                    -Recurse
                if ($errorMessage) { throw $errorMessage }
            }
        },
        @{
            Name = "release evidence directory"
            Action = {
                $errorMessage = Remove-OwnedPath `
                    -Path $ReleaseEvidenceDirectory `
                    -RuntimeRoot $Runtime `
                    -Recurse
                if ($errorMessage) { throw $errorMessage }
            }
        },
        @{
            Name = "Evidence smoke file"
            Action = {
                $errorMessage = Remove-OwnedPath `
                    -Path $EvidenceSmokeFile `
                    -RuntimeRoot $Runtime
                if ($errorMessage) { throw $errorMessage }
            }
        },
        @{
            Name = "file cleanup verification"
            Action = {
                $result.cleanup_files =
                    -not (Test-Path -LiteralPath $WebSmoke) -and
                    -not (Test-Path -LiteralPath $PytestTemp) -and
                    -not (Test-Path -LiteralPath $BackupSmokeDirectory) -and
                    -not (Test-Path -LiteralPath $ReleaseEvidenceDirectory) -and
                    -not (Test-Path -LiteralPath $EvidenceSmokeFile)
                if (-not $result.cleanup_files) {
                    throw "Disposable files remain after cleanup"
                }
            }
        }
    )
    $completion = Complete-G1Verification `
        -Result $result `
        -CleanupSteps $cleanupSteps `
        -ReportPath (Join-Path $Runtime "G1_VERIFICATION.json")
    if ($completion.failed) { exit 1 }
}
