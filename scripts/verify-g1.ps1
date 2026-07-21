param([switch]$UseExistingPostgres)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Runtime = Join-Path $Root ".runtime"
$Web = Join-Path $Root "web"
$WebSmoke = Join-Path $Runtime ("web-g1-" + [guid]::NewGuid().ToString("N"))
$PytestTemp = Join-Path $Runtime ("pytest-g1-" + [guid]::NewGuid().ToString("N"))
$BackupSmokeDirectory = Join-Path $Runtime ("backup-g1-" + [guid]::NewGuid().ToString("N"))
$DatabaseName = "kjds_g1_smoke"
$RestoreDatabaseName = "kjds_g1_restore"
$ApiPort = 8010
$WebPort = 3010
$EvidenceSmokeFile = Join-Path $Runtime ("g1-evidence-" + [guid]::NewGuid().ToString("N") + ".txt")
$BankEvidenceSmokeFile = Join-Path $Runtime ("g1-bank-evidence-" + [guid]::NewGuid().ToString("N") + ".txt")
$PilotResponseSmokeFile = Join-Path $Runtime ("g1-ozon-response-" + [guid]::NewGuid().ToString("N") + ".json")
$EpisodeSmokeFiles = @(
    Join-Path $Runtime ("g1-product-evidence-" + [guid]::NewGuid().ToString("N") + ".txt")
    Join-Path $Runtime ("g1-compliance-evidence-" + [guid]::NewGuid().ToString("N") + ".txt")
    Join-Path $Runtime ("g1-quality-evidence-" + [guid]::NewGuid().ToString("N") + ".txt")
)
$ImportSmokeFile = Join-Path $Runtime ("g1-orders-" + [guid]::NewGuid().ToString("N") + ".csv")
$FeeImportSmokeFile = Join-Path $Runtime ("g1-fees-" + [guid]::NewGuid().ToString("N") + ".csv")
$ApiProcess = $null
$WebProcess = $null
$PostgresContainer = $null
$WebContainer = $null
$Python = Join-Path $Root ".venv\Scripts\python.exe"

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
    $markers = @("--port $ApiPort", "--port $WebPort", $WebSmoke)
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
    backup_restore = $false
    backup_restore_sha256 = $null
    backup_restore_elapsed_seconds = $null
    backup_restore_counts = $null
    end_to_end_trace = $false
    connector_safety = $false
    runtime_identity_config = $false
    secret_scan = $false
    startup_package_contract = $false
    lint = $false
    tests = $false
    web_tests = $false
    web_build = $false
    container_import = $false
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
    candidate_demand_report_gate = $false
    research_signal_inbox = $false
    versioned_full_cost_template = $false
    actual_cost_authority_gate = $false
    actual_cost_authority_catalog = $false
    three_candidate_portfolio = $false
    evidence_backed_exception_workspace = $false
    interaction_profile_registry = $false
    decision_contract_compiler = $false
    decision_lifecycle = $false
    decision_calibration = $false
    causal_experiment_preregistration = $false
    causal_experiment_quality_gate = $false
    causal_experiment_value_model = $false
    causal_experiment_independent_review = $false
    causal_knowledge_registry = $false
    causal_policy_compiler = $false
    controlled_policy_rollout = $false
    causal_policy_evaluation_ledger = $false
    causal_policy_shadow_batch = $false
    causal_policy_approval_handoff = $false
    governed_execution_plan = $false
    governed_execution_dry_run = $false
    governed_execution_dual_control = $false
    limited_execution_command = $false
    limited_execution_receipt = $false
    compensating_rollback = $false
    post_execution_observation_contract = $false
    post_execution_guardrail_freeze = $false
    post_execution_rollback_trigger = $false
    capability_economic_ledger = $false
    operational_incident_auto_open = $false
    recovery_checklist = $false
    recovery_dual_control = $false
    recovery_drill = $false
    operations_sla_queue = $false
    operations_escalation_ledger = $false
    read_only_pilot_gate = $false
    read_only_pilot_dual_control = $false
    ozon_worker_contract_test = $false
    ozon_credential_isolation = $false
    ozon_pilot_preflight = $false
    ozon_worker_execution_intent = $false
    ozon_run_replay_guard = $false
    ozon_response_recovery = $false
    ozon_response_integrity = $false
    sku_episode_intake = $false
    passport_human_review = $false
    supplier_comparison_intake = $false
    procurement_dual_control = $false
    sample_procurement_lifecycle = $false
    supplier_performance_backup = $false
    sourcing_evidence_gate = $false
    operations_readiness = $false
    passport_evidence_gate = $false
    formal_fact_promotion = $false
    finance_fee_mapping_gate = $false
    finance_reconciliation = $false
    cash_forecast = $false
    web_health = $false
    web_proxy_auth = $false
    cleanup_processes = $false
    cleanup_database = $false
    cleanup_files = $false
    cleanup_file_errors = @()
    report = (Join-Path $Runtime "G1_VERIFICATION.json")
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

    $env:KJDS_DATABASE_URL = "postgresql+psycopg://hermes:hermes_dev@127.0.0.1:5432/$DatabaseName"
    $env:KJDS_DATABASE_PROVIDER = "local-postgres"
    # The gate must not inherit a machine-level cache path that a managed
    # runner cannot access. This override is scoped to this process only.
    $env:UV_CACHE_DIR = Join-Path $Runtime "uv-cache"

    if ($UseExistingPostgres) {
        Write-Output "[G-1] Using reachable PostgreSQL without Docker control-plane access"
        Invoke-External -Command $Python -Arguments @("scripts/manage_g1_database.py", "recreate")
    } else {
        Write-Output "[G-1] Starting PostgreSQL"
        Invoke-External -Command docker -Arguments @("compose", "up", "-d", "postgres")
        $PostgresContainer = (docker compose ps -q postgres).Trim()
        if (-not $PostgresContainer) { throw "PostgreSQL container was not created" }
        Wait-Until -Description "PostgreSQL health" -Condition {
            (docker inspect --format "{{.State.Health.Status}}" $PostgresContainer 2>$null).Trim() -eq "healthy"
        }
        Invoke-External -Command docker -Arguments @("exec", $PostgresContainer, "dropdb", "--if-exists", "-U", "hermes", $DatabaseName)
        Invoke-External -Command docker -Arguments @("exec", $PostgresContainer, "createdb", "-U", "hermes", $DatabaseName)
    }
    Write-Output "[G-1] Replaying migrations in disposable database"
    $env:KJDS_REPOSITORY = "postgres"
    $env:KJDS_SHADOW_MODE = "true"
    $env:KJDS_LIMITED_EXECUTION_ENABLED = "true"
    $env:KJDS_CONTROL_PLANE_URL = "http://127.0.0.1:$ApiPort"
    $env:KJDS_API_KEY = "g1-smoke-" + [guid]::NewGuid().ToString("N")
    $ApproverApiKey = "g1-approver-" + [guid]::NewGuid().ToString("N")
    $FinanceReviewerApiKey = "g1-finance-reviewer-" + [guid]::NewGuid().ToString("N")
    $KnowledgeApiKey = "g1-knowledge-" + [guid]::NewGuid().ToString("N")
    $ExecutorApiKey = "g1-executor-" + [guid]::NewGuid().ToString("N")
    $MonitorApiKey = "g1-monitor-" + [guid]::NewGuid().ToString("N")
    $env:KJDS_API_ACTOR = "g1-verifier"
    $env:KJDS_API_ROLES = "operator"
    $ApiCredentials = @{}
    $ApiCredentials[$env:KJDS_API_KEY] = @{ actor = "g1-verifier"; roles = @("operator", "reviewer", "admin") }
    $ApiCredentials[$ApproverApiKey] = @{ actor = "g1-independent-approver"; roles = @("reviewer", "approver") }
    $ApiCredentials[$FinanceReviewerApiKey] = @{ actor = "g1-finance-reviewer"; roles = @("reviewer") }
    $ApiCredentials[$KnowledgeApiKey] = @{ actor = "g1-knowledge-publisher"; roles = @("approver") }
    $ApiCredentials[$ExecutorApiKey] = @{ actor = "g1-ozon-worker"; roles = @("executor") }
    $ApiCredentials[$MonitorApiKey] = @{ actor = "g1-monitor-worker"; roles = @("monitor") }
    $env:KJDS_API_KEYS_JSON = $ApiCredentials | ConvertTo-Json -Compress
    $env:KJDS_MONITOR_API_KEY = $MonitorApiKey

    Invoke-External -Command uv -Arguments @("run", "python", "-m", "alembic", "upgrade", "head")
    $current = (uv run python -m alembic current).Trim()
    if ($LASTEXITCODE -ne 0 -or $current -notmatch "20260720_0038.*head") {
        throw "Unexpected migration head: $current"
    }
    $result.migration = "20260720_0038"

    Invoke-External -Command uv -Arguments @("run", "python", "-m", "alembic", "downgrade", "20260717_0024")
    $downgraded = (uv run python -m alembic current).Trim()
    if ($LASTEXITCODE -ne 0 -or $downgraded -notmatch "20260717_0024") {
        throw "Migration downgrade verification failed: $downgraded"
    }
    Invoke-External -Command uv -Arguments @("run", "python", "-m", "alembic", "upgrade", "head")
    $result.migration_replay = $true

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
    $result.ozon_worker_contract_test = $true
    $result.ozon_credential_isolation = $true

    Write-Output "[G-1] Running web security tests"
    Invoke-External -Command npm.cmd -Arguments @("--prefix", $Web, "test")
    $result.web_tests = $true

    Write-Output "[G-1] Building isolated web bundle"
    New-Item -ItemType Directory -Force $WebSmoke | Out-Null
    Copy-Item -LiteralPath (Join-Path $Web "app") -Destination $WebSmoke -Recurse
    Copy-Item -LiteralPath (Join-Path $Web "lib") -Destination $WebSmoke -Recurse
    foreach ($file in @("next-env.d.ts", "next.config.ts", "package.json", "package-lock.json", "tsconfig.json")) {
        Copy-Item -LiteralPath (Join-Path $Web $file) -Destination (Join-Path $WebSmoke $file)
    }
    New-Item -ItemType Junction -Path (Join-Path $WebSmoke "node_modules") -Target (Join-Path $Web "node_modules") | Out-Null
    Invoke-External -Command npm.cmd -Arguments @("--prefix", $WebSmoke, "run", "build", "--", "--webpack")
    $result.web_build = $true

    Write-Output "[G-1] Verifying production API image contains required runtime assets"
    Invoke-External -Command docker -Arguments @("compose", "build", "api", "web", "ozon-read-worker")
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

    $revalidationOutput = & docker compose run --rm --no-deps `
        -e KJDS_CONTROL_PLANE_URL=http://control.example.com `
        -e KJDS_PILOT_READER_API_KEY=g1-revalidate-pilot-reader `
        -e OZON_CLIENT_ID=g1-revalidate-seller-client `
        -e OZON_API_KEY=g1-revalidate-ozon-reader `
        ozon-read-worker python -m apps.control_plane.ozon_read_worker `
        --execute --pilot-id G1-REVALIDATE-PILOT --offer-id G1-REVALIDATE-OFFER `
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
        throw "Ozon Worker skipped execution-time revalidation or exposed credentials"
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
    $approverHeaders = @{ "X-KJDS-API-Key" = $ApproverApiKey }
    $financeReviewerHeaders = @{ "X-KJDS-API-Key" = $FinanceReviewerApiKey }
    $knowledgeHeaders = @{ "X-KJDS-API-Key" = $KnowledgeApiKey }
    $executorHeaders = @{ "X-KJDS-API-Key" = $ExecutorApiKey }
    $monitorHeaders = @{ "X-KJDS-API-Key" = $MonitorApiKey }
    $g1TraceId = "trace-g1-controlled-loop"
    $executionClaimHeaders = $executorHeaders.Clone()
    $executionClaimHeaders["X-Trace-ID"] = $g1TraceId
    $executionClaimHeaders["X-Request-ID"] = "req-g1-execution-claim"
    $executionReceiptHeaders = $executorHeaders.Clone()
    $executionReceiptHeaders["X-Trace-ID"] = $g1TraceId
    $executionReceiptHeaders["X-Request-ID"] = "req-g1-execution-receipt"
    $pilotStartHeaders = $headers.Clone()
    $pilotStartHeaders["X-Trace-ID"] = $g1TraceId
    $pilotStartHeaders["X-Request-ID"] = "req-g1-pilot-start"
    $pilotCompleteHeaders = $headers.Clone()
    $pilotCompleteHeaders["X-Trace-ID"] = $g1TraceId
    $pilotCompleteHeaders["X-Request-ID"] = "req-g1-pilot-complete"
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

    $product = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/products" -Method Post -Headers $headers -ContentType "application/json" -Body $body
    $readiness = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/products/$($product.id)/readiness" -Headers $headers
    $events = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/events" -Headers $headers
    if ($readiness.ready_for_validation -ne $false -or -not ($events | Where-Object aggregate_id -eq $product.id)) {
        throw "API write/read/event smoke failed"
    }
    $result.api_database_write = $true

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
    Set-Content -LiteralPath $BankEvidenceSmokeFile -Value "G-1 independent bank receipt evidence" -NoNewline -Encoding UTF8
    $bankEvidenceRecord = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/evidence" -Method Post -Headers $headers -Form @{
        file = Get-Item $BankEvidenceSmokeFile
        source = "g1_bank_export"
        source_ref = "g1://verification/bank-receipt"
        grade = "A"
        effective_at = "2026-07-16T00:00:00+08:00"
        metadata_json = '{"purpose":"G-1 finance reconciliation"}'
    }
    $lineage = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/evidence/$($evidenceRecord.id)/lineage" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        target_type = "product"
        target_id = $product.id
        relationship = "supports"
    } | ConvertTo-Json)
    if (-not $verification.valid -or $lineage.to_id -ne $product.id) {
        throw "Immutable evidence and lineage smoke failed"
    }
    $result.evidence_ledger = $true

    $demandReport = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operations/gate-evidence" -Method Post -Headers $headers -Form @{
        requirement_id = "SKU-000"
        effective_at = "2026-07-16T00:00:00+08:00"
        source_system = "ozon_data"
        report_window_days = 28
        file = Get-Item $EvidenceSmokeFile
    }
    $demandReview = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operations/demand-report-review" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body (@{
        report_evidence_id = $demandReport.evidence.id
        accepted = $true
        rationale = "G-1 independent demand report contract verification"
    } | ConvertTo-Json)
    if (
        $demandReport.review_status -ne "pending" -or
        $demandReview.review.metadata.decision -ne "accepted"
    ) {
        throw "Demand report dual-control smoke failed"
    }
    $result.candidate_demand_report_gate = $true

    $candidateRef = "g1-candidate-$sku"
    $candidateEvidence = @()
    foreach ($index in 1..5) {
        $family = if ($index -le 3) { "market.example" } else { "supplier.example" }
        $researchSignal = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/market/research-signals" -Method Post -Headers $headers -Form @{
            file = Get-Item $EvidenceSmokeFile
            provider = "g1_candidate_research"
            provider_record_id = "provider://$family/g1/candidate/$index"
            source_url = "https://$family/g1/candidate/$index"
            observed_at = "2026-07-16T00:00:00+08:00"
            declared_grade = "A"
            license_status = "verified"
            raw_fields_json = "{`"metric_index`":$index}"
            candidate_refs_json = "[`"$candidateRef`"]"
        }
        if (
            $researchSignal.decision_use -ne "auxiliary_only_pending_independent_authority_review" -or
            $researchSignal.automatic_listing -ne $false -or
            $researchSignal.automatic_procurement -ne $false -or
            -not ($researchSignal.candidate_refs -contains $candidateRef)
        ) {
            throw "Research signal inbox smoke failed"
        }
        $candidateEvidence += $researchSignal.evidence
    }
    $result.research_signal_inbox = $true
    $candidateMetrics = @("demand_signal", "competition_gap", "supplier_available", "compliance_redline", "return_risk")
    foreach ($index in 0..4) {
        $authorityReview = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/market/candidate-evidence/$($candidateEvidence[$index].id)/authority-review" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body (@{
            metric = $candidateMetrics[$index]
            approved_grade = "A"
            accepted = $true
            authentic_original = $true
            source_scope_matches = $true
            authority_basis_verified = $true
            rationale = "G-1 independent candidate evidence authority verification"
        } | ConvertTo-Json)
        $authorityStatus = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/market/candidate-evidence/$($candidateEvidence[$index].id)/authority-review?metric=$($candidateMetrics[$index])" -Headers $headers
        if (
            $authorityReview.review.metadata.decision -ne "accepted" -or
            $authorityStatus.status -ne "accepted" -or
            -not ($authorityStatus.accepted_grades -contains "A")
        ) {
            throw "Candidate evidence authority review smoke failed"
        }
    }
    $candidateName = "G-1 evidence-backed candidate"
    $candidateObservations = @(
        @{ metric = "demand_signal"; value = 70; confidence = 0.8; evidence_id = $candidateEvidence[0].id; window_days = 30; sample_size = 30 },
        @{ metric = "competition_gap"; value = 60; confidence = 0.8; evidence_id = $candidateEvidence[1].id; window_days = 30; sample_size = 30 },
        @{ metric = "supplier_available"; value = 1; confidence = 0.8; evidence_id = $candidateEvidence[2].id; window_days = 30; sample_size = 1 },
        @{ metric = "compliance_redline"; value = 0; confidence = 0.8; evidence_id = $candidateEvidence[3].id; window_days = 30; sample_size = 1 },
        @{ metric = "return_risk"; value = 20; confidence = 0.8; evidence_id = $candidateEvidence[4].id; window_days = 30; sample_size = 30 }
    )
    $candidateBase = @{
        candidate_ref = $candidateRef
        candidate_name = $candidateName
        market = "RU"
        category = "g1-verification"
        as_of = "2026-07-19T00:00:00+08:00"
        demand_report_evidence_id = $demandReport.evidence.id
        max_age_days = 90
    }
    $candidateIntakeBody = $candidateBase.Clone()
    $candidateIntakeBody.observations = $candidateObservations
    $candidateAssessment = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/market/candidates/intake" -Method Post -Headers $headers -ContentType "application/json" -Body ($candidateIntakeBody | ConvertTo-Json -Depth 6)
    $candidateHandoffBody = $candidateBase.Clone()
    $candidateHandoffBody.sku = "$sku-CAND"
    $candidateHandoffBody.confirmed = $true
    $candidateHandoff = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/market/candidates/sourcing-handoff" -Method Post -Headers $headers -ContentType "application/json" -Body ($candidateHandoffBody | ConvertTo-Json -Depth 5)
    $candidateHandoffRetry = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/market/candidates/sourcing-handoff" -Method Post -Headers $headers -ContentType "application/json" -Body ($candidateHandoffBody | ConvertTo-Json -Depth 5)
    $product = $candidateHandoff.product
    $candidateLineage = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/evidence/$($candidateEvidence[0].id)/lineage" -Headers $headers
    if (
        $candidateAssessment.decision -ne "request_three_quotes" -or
        $candidateAssessment.quote_policy_id -ne "ozon-ru-quote-screen-v1" -or
        $candidateAssessment.threshold_failures.Count -ne 0 -or
        $candidateHandoffRetry.product.id -ne $product.id -or
        $candidateHandoffRetry.created -ne $false -or
        -not ($candidateLineage | Where-Object { $_.to_type -eq "product" -and $_.to_id -eq $product.id -and $_.relationship -eq "candidate_basis" })
    ) {
        throw "Candidate sourcing handoff smoke failed"
    }
    $result.candidate_sourcing_handoff = $true

    $profiles = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/interaction-profiles" -Headers $headers
    $decisionProfile = $profiles | Where-Object { $_.id -eq "decision_review" }
    $bestSolutionProfile = $profiles | Where-Object { $_.id -eq "best_solution" }
    if (
        $profiles.Count -ne 6 -or
        "/x10think" -notin $decisionProfile.aliases -or
        "/oda" -notin $decisionProfile.aliases -or
        $decisionProfile.version -ne "1.0.0" -or
        "/best" -notin $bestSolutionProfile.aliases -or
        $bestSolutionProfile.version -ne "1.0.0"
    ) {
        throw "Versioned interaction profile registry smoke failed"
    }
    $result.interaction_profile_registry = $true

    $pendingContract = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/decision-contracts" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        profile = "/truth"
        objective = "Verify whether a market signal is causal"
        decision_domain = "market_intelligence"
        risk_level = "medium"
        unknowns = @("Full platform traffic is unavailable")
    } | ConvertTo-Json -Depth 5)
    $decisionBody = @{
        profile = "/x10think"
        objective = "Choose a controlled G-1 sample procurement path"
        decision_domain = "procurement"
        risk_level = "high"
        maximum_loss_amount = 30000
        currency = "CNY"
        options = @(
            @{ id = "A"; label = "Place a 100-unit sample order" },
            @{ id = "B"; label = "Do not place the sample order" }
        )
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 6
    $decisionContract = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/decision-contracts" -Method Post -Headers $headers -ContentType "application/json" -Body $decisionBody
    $decisionRetry = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/decision-contracts" -Method Post -Headers $headers -ContentType "application/json" -Body $decisionBody
    $decisionRegister = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/decision-contracts" -Headers $headers
    $decisionLineage = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/evidence/$($evidenceRecord.id)/lineage" -Headers $headers
    if (
        $pendingContract.status -ne "evidence_pending" -or
        $pendingContract.execution_eligible -ne $false -or
        $decisionContract.id -ne $decisionRetry.id -or
        $decisionContract.status -ne "ready_for_analysis" -or
        $decisionContract.execution_eligible -ne $false -or
        $decisionContract.requires_human_approval -ne $true -or
        $decisionContract.compiler_policy.model_may_execute -ne $false -or
        -not ($decisionRegister | Where-Object { $_.id -eq $decisionContract.id }) -or
        -not ($decisionLineage | Where-Object { $_.to_type -eq "decision_contract" -and $_.to_id -eq $decisionContract.id })
    ) {
        throw "Immutable evidence-gated decision contract compiler smoke failed"
    }
    $result.decision_contract_compiler = $true

    $analysisBody = @{
        conclusion = "The controlled 100-unit option has bounded downside and should be tested"
        confidence = 0.72
        recommended_option_id = "A"
        forecast_metric = "sample_cm3_cny"
        forecast_value = 12000
        forecast_low = 5000
        forecast_high = 18000
        forecast_unit = "CNY"
        forecast_due_at = "2026-07-18T00:00:00+00:00"
        assumptions = @("Freight remains within the evidence-backed range")
        unknowns = @("Observed return rate")
        evidence_ids = @($evidenceRecord.id)
        model_ref = "g1-deterministic-analysis"
    } | ConvertTo-Json -Depth 6
    $analysis = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/decision-contracts/$($decisionContract.id)/analyses" -Method Post -Headers $headers -ContentType "application/json" -Body $analysisBody
    $analysisRetry = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/decision-contracts/$($decisionContract.id)/analyses" -Method Post -Headers $headers -ContentType "application/json" -Body $analysisBody
    $selfReviewStatus = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/decision-analyses/$($analysis.id)/reviews" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        verdict = "accepted"
        rationale = "Self review must fail"
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $analysisReview = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/decision-analyses/$($analysis.id)/reviews" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body (@{
        verdict = "accepted"
        rationale = "Independent evidence and interval review passed"
        counterarguments = @("Freight can still rise")
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 5)
    $resolution = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/decision-contracts/$($decisionContract.id)/resolution" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body (@{
        analysis_id = $analysis.id
        disposition = "experiment"
        rationale = "Run only the bounded G-1 test"
        conditions = @("Maximum loss remains 30000 CNY")
    } | ConvertTo-Json -Depth 5)
    $outcome = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/decision-resolutions/$($resolution.id)/outcome" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        actual_value = 10000
        observed_at = "2026-07-19T00:00:00+00:00"
        evidence_ids = @($evidenceRecord.id)
        notes = "Observed G-1 outcome"
    } | ConvertTo-Json -Depth 4)
    $analysisLineage = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/evidence/$($evidenceRecord.id)/lineage" -Headers $headers
    if (
        $analysis.id -ne $analysisRetry.id -or
        $analysis.execution_eligible -ne $false -or
        $selfReviewStatus -ne 422 -or
        $analysisReview.reviewed_by -ne "g1-independent-approver" -or
        $resolution.execution_eligible -ne $false -or
        $resolution.decided_by -ne "g1-independent-approver" -or
        [decimal]$outcome.signed_error -ne -2000 -or
        $outcome.interval_covered -ne $true -or
        -not ($analysisLineage | Where-Object { $_.to_type -eq "decision_analysis" -and $_.to_id -eq $analysis.id }) -or
        -not ($analysisLineage | Where-Object { $_.to_type -eq "decision_outcome" -and $_.to_id -eq $outcome.id })
    ) {
        throw "Separated decision analysis, review, resolution, and outcome smoke failed"
    }
    $result.decision_lifecycle = $true

    $calibrationRows = @(Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/decision-calibration" -Headers $headers)
    $calibration = $calibrationRows | Where-Object { $_.metric -eq "sample_cm3_cny" -and $_.unit -eq "CNY" }
    if (
        $calibration.outcome_count -ne 1 -or
        [decimal]$calibration.mean_absolute_error -ne 2000 -or
        [decimal]$calibration.interval_coverage -ne 1
    ) {
        throw "Decision forecast calibration smoke failed"
    }
    $result.decision_calibration = $true

    $experimentBody = @{
        hypothesis = "The controlled treatment improves contribution profit per visitor"
        primary_metric = "cm3_per_visitor"
        randomization_unit = "visitor"
        interference_cluster = "product_family"
        variants = @(
            @{ id = "control"; label = "Current experience"; allocation = 0.5; control = $true },
            @{ id = "treatment"; label = "Candidate experience"; allocation = 0.5; control = $false }
        )
        target_sample_size = 20
        minimum_detectable_effect = 5
        budget_cap_amount = 1000
        stop_loss_amount = 300
        currency = "CNY"
        start_at = "2026-07-19T00:00:00+00:00"
        end_at = "2026-07-21T00:00:00+00:00"
        outcome_window_days = 7
        guardrails = @(
            @{ metric = "refund_rate"; direction = "max"; threshold = 0.1 }
        )
        stratification_keys = @("country_tier")
        effect_metrics = @(
            @{ metric = "cannibalized_cm3"; role = "cannibalization"; multiplier = -1; required = $true },
            @{ metric = "refund_cost_30d"; role = "long_term_cost"; multiplier = -1; required = $true }
        )
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 7
    $experiment = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/decision-resolutions/$($resolution.id)/experiment" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body $experimentBody
    $experimentRetry = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/decision-resolutions/$($resolution.id)/experiment" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body $experimentBody
    if (
        $experiment.id -ne $experimentRetry.id -or
        $experiment.status -ne "registered" -or
        $null -ne $experiment.assignment_seed -or
        $experiment.target_sample_size -ne 20 -or
        $experiment.stratification_keys[0] -ne "country_tier" -or
        $experiment.effect_metrics.Count -ne 3
    ) {
        throw "Immutable causal experiment preregistration smoke failed"
    }
    $result.causal_experiment_preregistration = $true

    $startBody = @{
        event_type = "started"
        effective_at = "2026-07-19T00:00:00+00:00"
        evidence_id = $evidenceRecord.id
        reason = "G-1 preregistration and guardrail review passed"
    } | ConvertTo-Json
    $startedExperiment = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-experiments/$($experiment.id)/events" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body $startBody
    $startRetry = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-experiments/$($experiment.id)/events" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body $startBody
    if ($startedExperiment.status -ne "running" -or $startRetry.events.Count -ne 1) {
        throw "Causal experiment lifecycle idempotency smoke failed"
    }
    $safeBudgetCheck = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-experiments/$($experiment.id)/safety-checks" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        metric = "budget_spend_amount"
        value = 900
        observed_at = "2026-07-19T01:00:00+00:00"
        evidence_id = $evidenceRecord.id
    } | ConvertTo-Json)
    if ($safeBudgetCheck.status -ne "within_limit") {
        throw "Causal experiment budget safety check smoke failed"
    }

    $observedCounts = @{ control = 0; treatment = 0 }
    for ($index = 0; $index -lt 100 -and ($observedCounts.control -lt 10 -or $observedCounts.treatment -lt 10); $index++) {
        $countryTier = if ($index % 2 -eq 0) { "tier_1" } else { "tier_2" }
        $assignment = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-experiments/$($experiment.id)/assignments" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
            unit_key = "g1-visitor-$index"
            assigned_at = "2026-07-20T00:00:00+00:00"
            strata = @{ country_tier = $countryTier }
        } | ConvertTo-Json)
        $variant = [string]$assignment.variant_id
        if ($observedCounts[$variant] -ge 10) { continue }
        $value = if ($variant -eq "control") { 100 + $observedCounts[$variant] % 2 } else { 110 + $observedCounts[$variant] % 2 }
        Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-experiment-assignments/$($assignment.id)/observation" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
            value = $value
            observed_at = "2026-07-22T00:00:00+00:00"
            evidence_id = $evidenceRecord.id
        } | ConvertTo-Json) | Out-Null
        foreach ($effectObservation in @(
            @{ metric = "cannibalized_cm3"; value = $(if ($variant -eq "control") { 0 } else { 5 }) },
            @{ metric = "refund_cost_30d"; value = $(if ($variant -eq "control") { 0 } else { 2 }) }
        )) {
            Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-experiment-assignments/$($assignment.id)/observation" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
                metric = $effectObservation.metric
                value = $effectObservation.value
                observed_at = "2026-07-22T00:00:00+00:00"
                evidence_id = $evidenceRecord.id
            } | ConvertTo-Json) | Out-Null
        }
        $observedCounts[$variant]++
    }
    $experimentEvaluation = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-experiments/$($experiment.id)/evaluation" -Headers $headers
    if (
        $observedCounts.control -ne 10 -or
        $observedCounts.treatment -ne 10 -or
        $experimentEvaluation.status -ne "ready_for_independent_review" -or
        $experimentEvaluation.review_eligible -ne $true -or
        $experimentEvaluation.decision_eligible -ne $false -or
        $experimentEvaluation.automatic_rollout -ne $false -or
        $experimentEvaluation.sample_ratio_mismatch -ne $false -or
        [decimal]$experimentEvaluation.treatment_effect.absolute_effect -ne 10 -or
        [decimal]$experimentEvaluation.incremental_value_per_unit -ne 3 -or
        $experimentEvaluation.missing_required_metrics.Count -ne 0 -or
        $experimentEvaluation.heterogeneous_effects[0].key -ne "country_tier"
    ) {
        throw "Causal experiment assignment, SRM, and review gate smoke failed"
    }
    $result.causal_experiment_value_model = $true
    $selfExperimentReview = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/causal-experiments/$($experiment.id)/reviews" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body (@{
        verdict = "accepted"
        rationale = "The experiment owner must not self-review"
        method_assessment = "Preregistered randomized design"
        data_quality_assessment = "SRM and completeness checks passed"
        counterarguments = @("Platform feedback may explain part of the effect")
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $causalReview = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-experiments/$($experiment.id)/reviews" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        verdict = "accepted"
        rationale = "Independent review accepts only the preregistered scope"
        method_assessment = "Randomization, interference boundary, and estimator are acceptable"
        data_quality_assessment = "No SRM and all required value metrics are complete"
        counterarguments = @("Platform feedback may explain part of the effect")
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    if ($selfExperimentReview -ne 422 -or $causalReview.verdict -ne "accepted" -or $causalReview.immutable -ne $true) {
        throw "Causal experiment independent review smoke failed"
    }
    $result.causal_experiment_independent_review = $true
    $causalKnowledgeEntry = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-experiments/$($experiment.id)/knowledge" -Method Post -Headers $knowledgeHeaders -ContentType "application/json" -Body (@{
        review_id = $causalReview.id
        claim = "The bounded treatment raises contribution margin per eligible visitor"
        mechanism = "Clearer value communication reduces comprehension cost and improves qualified conversion"
        applicability = @{ platform = "Ozon"; country = "RU"; category = "G1-smoke"; population = "eligible-visitors" }
        falsification_conditions = @("A later independent replication reverses direction", "Any preregistered safety guardrail breaches")
        evidence_ids = @($evidenceRecord.id)
        valid_from = "2026-07-17T00:00:00+00:00"
        reevaluate_at = "2027-07-17T00:00:00+00:00"
    } | ConvertTo-Json -Depth 5)
    if (
        $causalKnowledgeEntry.validity_status -ne "active" -or
        $causalKnowledgeEntry.knowledge_strength -ne "provisional" -or
        $causalKnowledgeEntry.usable -ne $true -or
        $causalKnowledgeEntry.execution_eligible -ne $false -or
        $causalKnowledgeEntry.automatic_rollout -ne $false
    ) {
        throw "Causal knowledge publication gate smoke failed"
    }
    $causalPolicy = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-policies" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        title = "G-1 knowledge-backed conditional policy"
        objective = "Recommend the validated listing only inside its evidence boundary"
        knowledge_ids = @($causalKnowledgeEntry.id)
        applicability = @{ platform = "Ozon"; country = "RU"; category = "G1-smoke"; population = "eligible-visitors" }
        conditions = @(@{ field = "inventory_cover_days"; operator = "gte"; value = 45 })
        action = @{ type = "recommend_listing_change"; parameters = @{ variant = "treatment" } }
        guardrails = @(@{ metric = "refund_rate"; direction = "max"; threshold = 0.1 })
        fallback_action = @{ type = "recommend_no_action"; parameters = @{ reason = "conditions_not_met" } }
        rollout_stages = @(
            @{ name = "shadow"; max_exposure_fraction = 0; minimum_observation_count = 20; minimum_incremental_value = 0 },
            @{ name = "limited_10_percent"; max_exposure_fraction = 0.1; minimum_observation_count = 100; minimum_incremental_value = 3 }
        )
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 7)
    $policyEvaluation = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-policies/$($causalPolicy.id)/evaluation" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        context = @{ platform = "Ozon"; country = "RU"; category = "G1-smoke"; population = "eligible-visitors"; inventory_cover_days = 60 }
    } | ConvertTo-Json -Depth 4)
    if (
        $causalPolicy.usable -ne $true -or
        $causalPolicy.execution_eligible -ne $false -or
        $policyEvaluation.matched -ne $true -or
        $policyEvaluation.recommendation.type -ne "recommend_listing_change" -or
        $policyEvaluation.automatic_execution -ne $false
    ) {
        throw "Knowledge-backed conditional policy compiler smoke failed"
    }
    $result.causal_policy_compiler = $true
    $policyReview = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-policies/$($causalPolicy.id)/reviews" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body (@{
        verdict = "accepted"
        rationale = "Conditions, fallback, guardrail, and rollout stages are bounded"
        counterarguments = @("A traffic mix shift can invalidate applicability")
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $shadowRelease = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-policies/$($causalPolicy.id)/releases" -Method Post -Headers $knowledgeHeaders -ContentType "application/json" -Body (@{
        review_id = $policyReview.id
        stage_index = 0
        rationale = "Approve zero-exposure shadow observation only"
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $prematureLimitedRelease = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/causal-policies/$($causalPolicy.id)/releases" -Method Post -Headers $knowledgeHeaders -ContentType "application/json" -Body (@{
        review_id = $policyReview.id
        stage_index = 1
        rationale = "Must fail before shadow outcome"
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $shadowContexts = @()
    foreach ($index in 0..19) {
        $shadowContexts += @{
            platform = "Ozon"
            country = "RU"
            category = "G1-smoke"
            population = "eligible-visitors"
            inventory_cover_days = $(if ($index -lt 12) { 60 } else { 30 })
        }
    }
    $shadowBatchBody = @{
        batch_key = "g1-shadow-batch"
        contexts = $shadowContexts
        observed_at = "2026-07-20T00:00:00+00:00"
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 6
    $shadowBatch = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-policy-releases/$($shadowRelease.id)/shadow-batches" -Method Post -Headers $headers -ContentType "application/json" -Body $shadowBatchBody
    $shadowBatchRetry = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-policy-releases/$($shadowRelease.id)/shadow-batches" -Method Post -Headers $headers -ContentType "application/json" -Body $shadowBatchBody
    $result.causal_policy_evaluation_ledger = ($shadowBatch.evaluation_ids.Count -eq 20)
    $result.causal_policy_shadow_batch = (
        $shadowBatch.id -eq $shadowBatchRetry.id -and
        $shadowBatch.zero_exposure -eq $true -and
        $shadowBatch.matched_count -eq 12 -and
        $shadowBatch.fallback_count -eq 8 -and
        $shadowBatch.execution_eligible -eq $false
    )
    if (-not $result.causal_policy_evaluation_ledger -or -not $result.causal_policy_shadow_batch) {
        throw "Immutable policy evaluation and zero-exposure shadow batch smoke failed"
    }
    $shadowOutcome = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-policy-releases/$($shadowRelease.id)/outcome" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        verdict = "passed"
        observation_count = 20
        incremental_value = 3
        guardrail_breached = $false
        notes = "Shadow result met the preregistered promotion gate"
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $limitedRelease = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-policies/$($causalPolicy.id)/releases" -Method Post -Headers $knowledgeHeaders -ContentType "application/json" -Body (@{
        review_id = $policyReview.id
        stage_index = 1
        rationale = "Previous immutable outcome met all promotion gates"
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $activationHandoff = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-policy-releases/$($limitedRelease.id)/activation-handoff" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        evaluation_ids = @($shadowBatch.evaluation_ids)
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $selfActivationApproval = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/approvals/$($activationHandoff.approval_id)/decision" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        approved = $true
        reason = "Self approval must fail"
    } | ConvertTo-Json)
    $approvedActivation = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/approvals/$($activationHandoff.approval_id)/decision" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body (@{
        approved = $true
        reason = "Independent evidence and guardrail review passed"
    } | ConvertTo-Json)
    $approvedHandoff = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-policy-activation-handoffs/$($activationHandoff.id)" -Headers $headers
    $executionStateHash = "a" * 64
    $executionPlanBody = @{
        idempotency_key = "g1-listing-draft-plan"
        adapter_id = "ozon.product.import.v3"
        target = @{ offer_id = "g1-ozon-offer" }
        precondition_state_hash = $executionStateHash
        intended_patch = @{ item = @{ offer_id = "g1-ozon-offer"; name = "G-1 validated candidate title" } }
        rollback_patch = @{ item = @{ offer_id = "g1-ozon-offer"; name = "G-1 current title" } }
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 5
    $executionPlan = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-policy-activation-handoffs/$($activationHandoff.id)/execution-plans" -Method Post -Headers $headers -ContentType "application/json" -Body $executionPlanBody
    $executionPlanRetry = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-policy-activation-handoffs/$($activationHandoff.id)/execution-plans" -Method Post -Headers $headers -ContentType "application/json" -Body $executionPlanBody
    $executionDryRun = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/governed-execution-plans/$($executionPlan.id)/dry-run" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        current_state_hash = $executionStateHash
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json)
    $selfExecutionApproval = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/approvals/$($executionPlan.approval_id)/decision" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        approved = $true
        reason = "Execution planner cannot self approve"
    } | ConvertTo-Json)
    $approvedExecution = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/approvals/$($executionPlan.approval_id)/decision" -Method Post -Headers $knowledgeHeaders -ContentType "application/json" -Body (@{
        approved = $true
        reason = "Independent target, snapshot, patch, and rollback review passed"
    } | ConvertTo-Json)
    $readyExecutionPlan = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/governed-execution-plans/$($executionPlan.id)" -Headers $headers
    $limitedCommand = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/governed-execution-plans/$($executionPlan.id)/commands" -Method Post -Headers $headers
    $limitedCommandRetry = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/governed-execution-plans/$($executionPlan.id)/commands" -Method Post -Headers $headers
    $claimedCommand = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/limited-execution-commands/$($limitedCommand.id)/claim" -Method Post -Headers $executionClaimHeaders -ContentType "application/json" -Body (@{
        current_state_hash = $executionStateHash
        lease_seconds = 120
    } | ConvertTo-Json)
    $resultingExecutionHash = "b" * 64
    $executionReceipt = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/limited-execution-commands/$($limitedCommand.id)/receipt" -Method Post -Headers $executionReceiptHeaders -ContentType "application/json" -Body (@{
        outcome = "succeeded"
        remote_operation_id = "g1-simulated-ozon-operation"
        resulting_state_hash = $resultingExecutionHash
        mutation_applied = $true
        error_code = $null
        error_detail = $null
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $observationWindow = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/limited-execution-commands/$($limitedCommand.id)/observation-window" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        primary_metric = "contribution_profit_per_visitor"
        baseline = @{ contribution_profit_per_visitor = 10; refund_rate = 0.04 }
        required_observations = 2
        starts_at = "2026-07-17T00:00:00+00:00"
        ends_at = "2026-07-18T00:00:00+00:00"
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $safeObservation = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/execution-observation-windows/$($observationWindow.id)/observations" -Method Post -Headers $monitorHeaders -ContentType "application/json" -Body (@{
        metric = "contribution_profit_per_visitor"
        value = 12
        observed_at = "2026-07-17T12:00:00+00:00"
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $guardrailObservation = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/execution-observation-windows/$($observationWindow.id)/observations" -Method Post -Headers $monitorHeaders -ContentType "application/json" -Body (@{
        metric = "refund_rate"
        value = 0.11
        observed_at = "2026-07-17T13:00:00+00:00"
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $observationEvaluation = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/execution-observation-windows/$($observationWindow.id)/evaluation?as_of=2026-07-19T00:00:00%2B00:00" -Headers $headers
    $postExecutionSwitch = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/system/kill-switch" -Headers $headers
    $rollbackCommand = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/limited-execution-commands/$($guardrailObservation.rollback_command_id)" -Headers $headers
    $incident = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operational-incidents/$($guardrailObservation.incident_id)" -Headers $headers
    $operationsAsOf = (Get-Date).ToUniversalTime().AddHours(1).ToString("o")
    $operationsQueueDuringIncident = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operations-control/queue?as_of=$([uri]::EscapeDataString($operationsAsOf))" -Headers $headers
    $operationsScan = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operations-control/escalation-scan" -Method Post -Headers $monitorHeaders -ContentType "application/json" -Body (@{
        as_of = $operationsAsOf
    } | ConvertTo-Json)
    $operationsScanRetry = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operations-control/escalation-scan" -Method Post -Headers $monitorHeaders -ContentType "application/json" -Body (@{
        as_of = $operationsAsOf
    } | ConvertTo-Json)
    $operationsEscalations = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operations-control/escalations" -Headers $headers
    $claimedIncident = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operational-incidents/$($incident.id)/claim" -Method Post -Headers $headers
    $recoveryChecks = @(
        "remote_state_reconciled",
        "rollback_confirmed_or_not_required",
        "data_reconciled",
        "credentials_rotated_or_not_required",
        "monitoring_restored"
    )
    foreach ($check in $recoveryChecks) {
        $checkedIncident = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operational-incidents/$($incident.id)/checks" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
            check = $check
            passed = $true
            notes = "G-1 verified $check while production writes remained frozen"
            evidence_ids = @($evidenceRecord.id)
        } | ConvertTo-Json -Depth 4)
    }
    $pendingIncidentReview = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operational-incidents/$($incident.id)/review-request" -Method Post -Headers $headers
    $selfIncidentReview = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/operational-incidents/$($incident.id)/review" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        accepted = $true
        rationale = "Self review must be rejected"
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $reviewedIncident = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operational-incidents/$($incident.id)/review" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body (@{
        accepted = $true
        rationale = "Independent reviewer confirmed every recovery check"
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $prematureIncidentClose = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/operational-incidents/$($incident.id)/close" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        notes = "Closure must fail while the kill switch remains engaged"
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $postExecutionRelease = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/system/kill-switch/release" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        reason = "G-1 independent recovery review passed; allow queued compensation only"
    } | ConvertTo-Json)
    $claimedRollback = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/limited-execution-commands/$($rollbackCommand.id)/claim" -Method Post -Headers $executorHeaders -ContentType "application/json" -Body (@{
        current_state_hash = $resultingExecutionHash
        lease_seconds = 120
    } | ConvertTo-Json)
    $rollbackReceipt = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/limited-execution-commands/$($rollbackCommand.id)/receipt" -Method Post -Headers $executorHeaders -ContentType "application/json" -Body (@{
        outcome = "succeeded"
        remote_operation_id = "g1-simulated-ozon-rollback"
        resulting_state_hash = $executionStateHash
        mutation_applied = $true
        error_code = $null
        error_detail = $null
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $closedIncident = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operational-incidents/$($incident.id)/close" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        notes = "Compensating rollback confirmed and incident history preserved"
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $drillIncident = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operational-incidents" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        idempotency_key = "g1-quarterly-recovery-drill"
        mode = "drill"
        severity = "high"
        trigger_type = "simulated_ozon_api_outage"
        source_type = $null
        source_id = $null
        summary = "G-1 simulated Ozon API outage recovery drill"
        impact = @("simulated:ozon-worker")
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $claimedDrill = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operational-incidents/$($drillIncident.id)/claim" -Method Post -Headers $headers
    foreach ($check in $recoveryChecks) {
        $checkedDrill = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operational-incidents/$($drillIncident.id)/checks" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
            check = $check
            passed = $true
            notes = "G-1 drill verified $check without production mutation"
            evidence_ids = @($evidenceRecord.id)
        } | ConvertTo-Json -Depth 4)
    }
    $pendingDrillReview = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operational-incidents/$($drillIncident.id)/review-request" -Method Post -Headers $headers
    $reviewedDrill = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operational-incidents/$($drillIncident.id)/review" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body (@{
        accepted = $true
        rationale = "Independent reviewer accepted the recovery drill"
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $closedDrill = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operational-incidents/$($drillIncident.id)/close" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        notes = "Drill completed without engaging production kill switch"
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $readOnlyPilot = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/read-only-pilots" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        idempotency_key = "g1-ozon-read-only-pilot"
        platform = "ozon"
        account_alias = "g1-ozon-ru-main"
        # The first production adapter is intentionally product-read only.
        # Inventory/orders/analytics/finance remain contract-only until their
        # dedicated worker scope is implemented and independently verified.
        allowed_operations = @("ozon.product.read")
        max_daily_requests = 100
        max_targets = 10
        starts_at = "2026-07-17T00:00:00+00:00"
        ends_at = "2026-07-20T00:00:00+00:00"
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $pilotControls = @(
        "credentials_isolated",
        "least_privilege_scope",
        "monitoring_configured",
        "data_export_backup_verified"
    )
    foreach ($control in $pilotControls) {
        $attestedPilot = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/read-only-pilots/$($readOnlyPilot.id)/attestations" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
            control = $control
            passed = $true
            notes = "G-1 verified $control without storing credentials"
            evidence_ids = @($evidenceRecord.id)
        } | ConvertTo-Json -Depth 4)
    }
    $pilotEvaluation = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/read-only-pilots/$($readOnlyPilot.id)/evaluation?as_of=2026-07-17T14:00:00%2B00:00" -Headers $headers
    $pendingPilotReview = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/read-only-pilots/$($readOnlyPilot.id)/review-request" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        as_of = "2026-07-17T14:00:00+00:00"
    } | ConvertTo-Json)
    $selfPilotReview = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/read-only-pilots/$($readOnlyPilot.id)/review" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        accepted = $true
        rationale = "Self review must be rejected"
    } | ConvertTo-Json)
    $approvedPilot = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/read-only-pilots/$($readOnlyPilot.id)/review" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body (@{
        accepted = $true
        rationale = "Independent reviewer confirmed read-only scope and all controls"
    } | ConvertTo-Json)
    $activePilot = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/read-only-pilots/$($readOnlyPilot.id)/activate" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        as_of = "2026-07-17T14:00:00+00:00"
    } | ConvertTo-Json)
    $pilotRun = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/read-only-pilots/$($readOnlyPilot.id)/runs" -Method Post -Headers $pilotStartHeaders -ContentType "application/json" -Body (@{
        idempotency_key = "g1-read-only-claim-run"
        operation = "ozon.product.read"
        target_ref = "G1-SYNTHETIC-OFFER"
        as_of = "2026-07-17T14:00:00+00:00"
    } | ConvertTo-Json)
    $stateHash = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    Set-Content -LiteralPath $PilotResponseSmokeFile -Value '{"schema_version":"ozon-response-bundle-v2","contract_version":"ozon-product-read-v1","responses":[]}' -NoNewline -Encoding UTF8
    $pilotResponseBytes = [System.IO.File]::ReadAllBytes($PilotResponseSmokeFile)
    $pilotResponseSha = ([System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::HashData($pilotResponseBytes))).Replace("-", "").ToLowerInvariant()
    $pilotSummaryJson = (@{
        contract_version = "ozon-product-read-v1"
        state_sha256 = $stateHash
        info_item_count = 1
        attribute_item_count = 1
    } | ConvertTo-Json -Compress)
    $pilotCheckpoint = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/read-only-pilot-runs/$($pilotRun.id)/response-checkpoint" -Method Post -Headers $pilotCompleteHeaders -Form @{
        file = Get-Item $PilotResponseSmokeFile
        response_sha256 = $pilotResponseSha
        response_byte_size = $pilotResponseBytes.Length
        record_count = 2
        summary_json = $pilotSummaryJson
    }
    $pilotCheckpointReplay = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/read-only-pilot-runs/$($pilotRun.id)/response-checkpoint" -Method Post -Headers $pilotCompleteHeaders -Form @{
        file = Get-Item $PilotResponseSmokeFile
        response_sha256 = $pilotResponseSha
        response_byte_size = $pilotResponseBytes.Length
        record_count = 2
        summary_json = $pilotSummaryJson
    }
    $completedPilotRun = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/read-only-pilot-runs/$($pilotRun.id)/finalize" -Method Post -Headers $pilotCompleteHeaders
    $completedPilotRunReplay = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/read-only-pilot-runs/$($pilotRun.id)/finalize" -Method Post -Headers $pilotCompleteHeaders
    $pilotRunReplay = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/read-only-pilots/$($readOnlyPilot.id)/runs" -Method Post -Headers $pilotStartHeaders -ContentType "application/json" -Body (@{
        idempotency_key = "g1-read-only-claim-run"
        operation = "ozon.product.read"
        target_ref = "G1-SYNTHETIC-OFFER"
        as_of = "2026-07-17T14:01:00+00:00"
    } | ConvertTo-Json)
    $result.end_to_end_trace = (
        $executionReceipt.command_id -eq $limitedCommand.id -and
        $executionReceipt.request_id -eq "req-g1-execution-receipt" -and
        $executionReceipt.trace_id -eq $g1TraceId -and
        $pilotRun.request_id -eq "req-g1-pilot-start" -and
        $pilotRun.trace_id -eq $g1TraceId -and
        $pilotRun.execution_granted -eq $true -and
        $pilotRun.idempotency_replay -eq $false -and
        $completedPilotRun.id -eq $pilotRun.id -and
        $completedPilotRun.trace_id -eq $g1TraceId -and
        $completedPilotRun.raw_response_stored -eq $true -and
        $completedPilotRun.raw_response_verified -eq $true -and
        $completedPilotRun.raw_response_integrity_code -eq $null -and
        $pilotCheckpoint.status -eq "response_captured" -and
        $pilotCheckpoint.recovery_pending -eq $true -and
        $pilotCheckpoint.raw_response_verified -eq $true -and
        $pilotCheckpoint.checkpoint_evidence_id -eq $pilotCheckpointReplay.checkpoint_evidence_id -and
        $completedPilotRun.raw_response_evidence_id -eq $pilotCheckpoint.checkpoint_evidence_id -and
        $completedPilotRun.evidence_id -and
        $completedPilotRunReplay.evidence_id -eq $completedPilotRun.evidence_id -and
        $pilotRunReplay.id -eq $pilotRun.id -and
        $pilotRunReplay.status -eq "completed" -and
        $pilotRunReplay.execution_granted -eq $false -and
        $pilotRunReplay.idempotency_replay -eq $true
    )
    if (-not $result.end_to_end_trace) {
        throw "End-to-end request, trace, run, command, and evidence correlation failed"
    }
    $result.connector_safety = (
        $pilotCheckpoint.response_sha256 -eq $pilotResponseSha -and
        $pilotCheckpoint.response_byte_size -eq $pilotResponseBytes.Length -and
        $completedPilotRun.response_sha256 -eq $pilotResponseSha
    )
    if (-not $result.connector_safety) {
        throw "Ozon connector response evidence safety contract failed"
    }
    $result.ozon_run_replay_guard = $true
    $result.ozon_response_recovery = $true
    $result.ozon_response_integrity = $true
    $claimBody = @{
        idempotency_key = "g1-read-only-claim"
        claim_type = "inventory_observation"
        payload = @{ stock_count = 12; currency_code = "RUB" }
        source_state_sha256 = $stateHash
        effective_at = "2026-07-17T14:00:00+00:00"
    } | ConvertTo-Json -Depth 5
    $claim = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/read-only-pilot-runs/$($pilotRun.id)/claims" -Method Post -Headers $headers -ContentType "application/json" -Body $claimBody
    $claimRetry = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/read-only-pilot-runs/$($pilotRun.id)/claims" -Method Post -Headers $headers -ContentType "application/json" -Body $claimBody
    $selfClaimReview = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/read-only-claims/$($claim.id)/review" -Method Post -Headers $headers -ContentType "application/json" -Body (@{ decision = "accepted"; rationale = "Self review must fail" } | ConvertTo-Json)
    $reviewedClaim = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/read-only-claims/$($claim.id)/review" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body (@{ decision = "accepted"; rationale = "Synthetic read evidence reviewed independently" } | ConvertTo-Json)
    if ($pilotRun.status -ne "started" -or $completedPilotRun.outcome -ne "succeeded" -or $claim.id -ne $claimRetry.id -or $claim.status -ne "pending_review" -or $selfClaimReview -ne 422 -or $reviewedClaim.status -ne "accepted" -or $reviewedClaim.formal_fact_promoted -ne $false) {
        throw "Read-only claim bridge smoke failed"
    }
    $result.read_only_claim_bridge = $true
    $capabilityAssessment = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/execution-observation-windows/$($observationWindow.id)/capability-economics" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        realized_incremental_value = -20
        avoided_loss = 5
        model_compute_cost = 1
        human_review_cost = 2
        incident_loss = 10
        maintenance_cost = 1
        currency = "CNY"
        evidence_ids = @($evidenceRecord.id)
        as_of = "2026-07-19T00:00:00+00:00"
    } | ConvertTo-Json -Depth 4)
    $capabilitySummaries = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/capability-economic-summaries" -Headers $headers
    if (
        $policyReview.verdict -ne "accepted" -or
        $shadowRelease.stage.max_exposure_fraction -ne "0" -or
        $shadowRelease.execution_eligible -ne $false -or
        $prematureLimitedRelease -ne 422 -or
        $shadowOutcome.verdict -ne "passed" -or
        $limitedRelease.stage.max_exposure_fraction -ne "0.1" -or
        $limitedRelease.automatic_promotion -ne $false -or
        $activationHandoff.approval_status -ne "pending" -or
        $selfActivationApproval -ne 422 -or
        $approvedActivation.status -ne "approved" -or
        $approvedHandoff.activation_eligible -ne $true -or
        $approvedHandoff.execution_eligible -ne $false
    ) {
        throw "Controlled conditional policy rollout smoke failed"
    }
    $result.controlled_policy_rollout = $true
    $result.causal_policy_approval_handoff = $true
    $result.governed_execution_plan = (
        $executionPlan.id -eq $executionPlanRetry.id -and
        $executionPlan.live_execution_supported -eq $true -and
        $executionPlan.execution_eligible -eq $false
    )
    $result.governed_execution_dry_run = (
        $executionDryRun.passed -eq $true -and
        $executionDryRun.platform_write_performed -eq $false
    )
    $result.governed_execution_dual_control = (
        $selfExecutionApproval -eq 422 -and
        $approvedExecution.status -eq "approved" -and
        $readyExecutionPlan.ready_for_executor -eq $true -and
        $readyExecutionPlan.execution_eligible -eq $false
    )
    if (
        -not $result.governed_execution_plan -or
        -not $result.governed_execution_dry_run -or
        -not $result.governed_execution_dual_control
    ) {
        throw "Governed reversible execution planning smoke failed"
    }
    $result.limited_execution_command = (
        $limitedCommand.id -eq $limitedCommandRetry.id -and
        $limitedCommand.status -eq "queued" -and
        $claimedCommand.status -eq "claimed" -and
        $claimedCommand.idempotency_token.Length -eq 64
    )
    $result.limited_execution_receipt = (
        $executionReceipt.outcome -eq "succeeded" -and
        $executionReceipt.mutation_applied -eq $true
    )
    $result.post_execution_observation_contract = (
        $observationWindow.command_id -eq $limitedCommand.id -and
        $observationWindow.immutable_contract -eq $true -and
        $safeObservation.guardrail_breached -eq $false -and
        $observationWindow.automatic_policy_promotion -eq $false
    )
    $result.post_execution_guardrail_freeze = (
        $guardrailObservation.guardrail_breached -eq $true -and
        $observationEvaluation.status -eq "guardrail_breached" -and
        $observationEvaluation.kill_switch_engaged -eq $true -and
        $postExecutionSwitch.engaged -eq $true -and
        $postExecutionRelease.engaged -eq $false
    )
    $result.post_execution_rollback_trigger = (
        $guardrailObservation.rollback_command_id -eq $rollbackCommand.id -and
        $observationEvaluation.rollback_queued -eq $true
    )
    $result.capability_economic_ledger = (
        [decimal]$capabilityAssessment.net_value -eq -29 -and
        $capabilityAssessment.automatic_authority_change -eq $false -and
        $capabilitySummaries.Count -eq 1 -and
        $capabilitySummaries[0].governance_recommendation -eq "restrict_and_review" -and
        $capabilitySummaries[0].automatic_authority_change -eq $false
    )
    Write-Output "[G-1] Verifying policy and capability numeric integrity on PostgreSQL"
    Invoke-External -Command uv -Arguments @("run", "python", "scripts/verify_policy_capability_integrity_postgres.py")
    $result.policy_capability_numeric_integrity = $true
    $result.operational_incident_auto_open = (
        $guardrailObservation.incident_id -eq $incident.id -and
        $incident.trigger_type -eq "post_execution_guardrail_breached" -and
        $incident.status -eq "contained" -and
        $incident.automatic_release -eq $false
    )
    $result.recovery_checklist = (
        $claimedIncident.status -eq "recovering" -and
        @($checkedIncident.checks.PSObject.Properties).Count -eq 5 -and
        $pendingIncidentReview.status -eq "pending_review"
    )
    $result.recovery_dual_control = (
        $selfIncidentReview -eq 422 -and
        $reviewedIncident.status -eq "ready_for_release" -and
        $prematureIncidentClose -eq 422 -and
        $closedIncident.status -eq "closed"
    )
    $result.recovery_drill = (
        $drillIncident.mode -eq "drill" -and
        $claimedDrill.status -eq "recovering" -and
        @($checkedDrill.checks.PSObject.Properties).Count -eq 5 -and
        $pendingDrillReview.status -eq "pending_review" -and
        $reviewedDrill.status -eq "ready_for_release" -and
        $closedDrill.status -eq "closed" -and
        $closedDrill.kill_switch_engaged -eq $false
    )
    $result.operations_sla_queue = (
        @($operationsQueueDuringIncident).Count -ge 2 -and
        @($operationsQueueDuringIncident | Where-Object { $_.item_type -eq "incident" -and $_.overdue -eq $true }).Count -eq 1 -and
        @($operationsQueueDuringIncident | Where-Object { $_.item_type -eq "execution_command" }).Count -ge 1
    )
    $result.operations_escalation_ledger = (
        $operationsScan.overdue_count -ge 2 -and
        @($operationsScan.new_escalation_ids).Count -ge 2 -and
        $operationsScan.automatic_business_action -eq $false -and
        @($operationsScanRetry.new_escalation_ids).Count -eq 0 -and
        @($operationsEscalations).Count -ge 2
    )
    $result.read_only_pilot_gate = (
        $pilotEvaluation.ready_for_review -eq $true -and
        $pilotEvaluation.platform_write_allowed -eq $false -and
        @($attestedPilot.controls.PSObject.Properties).Count -eq 4 -and
        $activePilot.status -eq "active" -and
        $activePilot.platform_write_allowed -eq $false -and
        $activePilot.execution_eligible -eq $false -and
        $activePilot.credential_material_stored -eq $false
    )
    $result.read_only_pilot_dual_control = (
        $pendingPilotReview.status -eq "pending_review" -and
        $selfPilotReview -eq 422 -and
        $approvedPilot.status -eq "approved" -and
        $approvedPilot.reviewed_by -eq "g1-independent-approver"
    )
    $result.compensating_rollback = (
        $rollbackCommand.command_kind -eq "rollback" -and
        $rollbackCommand.expected_state_hash -eq $resultingExecutionHash -and
        $claimedRollback.status -eq "claimed" -and
        $rollbackReceipt.outcome -eq "succeeded"
    )
    if (
        -not $result.limited_execution_command -or
        -not $result.limited_execution_receipt -or
        -not $result.post_execution_observation_contract -or
        -not $result.post_execution_guardrail_freeze -or
        -not $result.post_execution_rollback_trigger -or
        -not $result.capability_economic_ledger -or
        -not $result.policy_capability_numeric_integrity -or
        -not $result.operational_incident_auto_open -or
        -not $result.recovery_checklist -or
        -not $result.recovery_dual_control -or
        -not $result.recovery_drill -or
        -not $result.operations_sla_queue -or
        -not $result.operations_escalation_ledger -or
        -not $result.read_only_pilot_gate -or
        -not $result.read_only_pilot_dual_control -or
        -not $result.compensating_rollback
    ) {
        throw "Limited execution, incident recovery, drill, and rollback smoke failed"
    }
    $breachedGuardrail = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-experiments/$($experiment.id)/safety-checks" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        metric = "refund_rate"
        value = 0.11
        observed_at = "2026-07-22T01:00:00+00:00"
        evidence_id = $evidenceRecord.id
    } | ConvertTo-Json)
    $blockedAssignment = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/causal-experiments/$($experiment.id)/assignments" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        unit_key = "g1-visitor-after-safety-breach"
        assigned_at = "2026-07-20T00:00:00+00:00"
        strata = @{ country_tier = "tier_1" }
    } | ConvertTo-Json)
    $breachedEvaluation = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-experiments/$($experiment.id)/evaluation" -Headers $headers
    $invalidatedKnowledge = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-knowledge/$($causalKnowledgeEntry.id)" -Headers $headers
    $invalidatedPolicy = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-policies/$($causalPolicy.id)" -Headers $headers
    $invalidatedHandoff = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/causal-policy-activation-handoffs/$($activationHandoff.id)" -Headers $headers
    $invalidatedExecutionPlan = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/governed-execution-plans/$($executionPlan.id)" -Headers $headers
    if (
        $breachedGuardrail.status -ne "breached" -or
        $blockedAssignment -ne 422 -or
        $breachedEvaluation.status -ne "safety_breach" -or
        $breachedEvaluation.safety_gate_breached -ne $true -or
        $breachedEvaluation.review_eligible -ne $false -or
        $breachedEvaluation.automatic_rollout -ne $false -or
        $invalidatedKnowledge.validity_status -ne "source_experiment_invalidated" -or
        $invalidatedKnowledge.usable -ne $false -or
        $invalidatedPolicy.validity_status -ne "source_knowledge_invalidated" -or
        $invalidatedPolicy.usable -ne $false -or
        $invalidatedHandoff.validity_status -ne "source_policy_invalidated" -or
        $invalidatedHandoff.activation_eligible -ne $false -or
        $invalidatedExecutionPlan.ready_for_executor -ne $false -or
        $invalidatedExecutionPlan.handoff_validity_status -ne "source_policy_invalidated"
    ) {
        throw "Causal experiment stop-loss and guardrail freeze smoke failed"
    }
    $result.causal_experiment_quality_gate = $true
    $result.causal_knowledge_registry = $true

    foreach ($requirementId in @("GOV-001", "OZN-001")) {
        Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operations/gate-evidence" -Method Post -Headers $headers -Form @{
            file = Get-Item $EvidenceSmokeFile
            requirement_id = $requirementId
            effective_at = "2026-07-16T00:00:00+08:00"
        } | Out-Null
    }

    $gateReviewBody = @{
        idempotency_key = "g1-structured-g0-review"
        gate_id = "G0"
        owner_id = "g1-verifier"
        approver_id = "g1-independent-approver"
        participants = @("g1-verifier", "g1-independent-approver", "g1-knowledge-publisher")
        objective = "Confirm the G0 operating boundary before controlled SKU and Ozon work."
        exit_criteria = "Owner, independent approver, evidence, risk budget, maximum loss, and rollback are explicit."
        deliverables = @("G0 evidence pack", "Read-only pilot boundary")
        evidence_ids = @()
        unknowns = @("Live Ozon settlement sample")
        blockers = @()
        risk_budget = @{ amount = "10000"; currency = "CNY" }
        max_loss = @{ amount = "3000"; currency = "CNY" }
        rollback_plan = "Stop all writes, preserve evidence, and return to read-only mode."
    } | ConvertTo-Json -Depth 6
    $gateReview = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/governance/gate-reviews" -Method Post -Headers $headers -ContentType "application/json" -Body $gateReviewBody
    $gateReviewRetry = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/governance/gate-reviews" -Method Post -Headers $headers -ContentType "application/json" -Body $gateReviewBody
    $submittedGateReview = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/governance/gate-reviews/$($gateReview.id)/submit" -Method Post -Headers $headers -ContentType "application/json" -Body (@{ evidence_ids = @($evidenceRecord.id) } | ConvertTo-Json)
    $decidedGateReview = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/governance/gate-reviews/$($gateReview.id)/decide" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body (@{ decision = "CONDITIONAL"; rationale = "G0 is bounded; live finance evidence remains a G4 condition."; conditions = @("Attach live settlement evidence before G4.") } | ConvertTo-Json)
    if ($gateReview.id -ne $gateReviewRetry.id -or $submittedGateReview.status -ne "submitted" -or $decidedGateReview.decision -ne "CONDITIONAL") {
        throw "Structured G0 gate review smoke failed"
    }
    $result.governance_gate_review = $true

    $episodeSku = "G1-EPISODE-" + [guid]::NewGuid().ToString("N")
    @("product evidence", "compliance evidence", "quality evidence") | ForEach-Object -Begin { $index = 0 } -Process {
        Set-Content -LiteralPath $EpisodeSmokeFiles[$index] -Value $_ -NoNewline -Encoding UTF8
        $index++
    }
    $episodeForm = @{
        sku = $episodeSku
        name = "G-1 episode intake product"
        effective_at = "2026-07-16T00:00:00+08:00"
        product_facts_json = (@{
            decision = "draft"; material = "verification"; intended_use = "verification"
            country_of_origin = "CN"; weight_kg = "0.5"
            dimensions_cm = @{ length = 30; width = 20; height = 10 }
        } | ConvertTo-Json -Depth 4 -Compress)
        compliance_facts_json = (@{
            decision = "draft"; hs_code = "verification"; eaeu_rules = @("verification")
            eac_requirement = "unknown"; chestny_znak_requirement = "unknown"
            russian_labeling = "unknown"; ip_status = "review_required"
            transport_restrictions = "unknown"; sellability = "pending_review"
        } | ConvertTo-Json -Depth 4 -Compress)
        quality_facts_json = (@{
            decision = "draft"; golden_sample_ref = "g1://sample"
            inspection_plan = @("verification"); packaging_test = "pending"
        } | ConvertTo-Json -Depth 4 -Compress)
        product_evidence = Get-Item $EpisodeSmokeFiles[0]
        compliance_evidence = Get-Item $EpisodeSmokeFiles[1]
        quality_evidence = Get-Item $EpisodeSmokeFiles[2]
    }
    $episode = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/intake/sku-episodes" -Method Post -Headers $headers -Form $episodeForm
    $episodeRetry = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/intake/sku-episodes" -Method Post -Headers $headers -Form $episodeForm
    $episodeLineage = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/evidence/$($episode.evidence[0].id)/lineage" -Headers $headers
    if (
        $episode.product.id -ne $episodeRetry.product.id -or
        $episode.passports.Count -ne 3 -or
        @($episode.readiness.passports | Where-Object { $_.status -ne "draft" }).Count -ne 0 -or
        -not ($episodeLineage | Where-Object { $_.to_type -eq "passport" -and $_.to_id -eq $episode.passports[0].id })
    ) {
        throw "Idempotent SKU episode intake smoke failed"
    }
    $result.sku_episode_intake = $true

    $reviewQueue = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/passport-reviews" -Headers $headers
    $productReview = $reviewQueue | Where-Object { $_.product.id -eq $episode.product.id -and $_.passport.kind -eq "product" }
    $reviewBody = @{
        expected_version = $productReview.passport.version
        decision = "approved"
        review_notes = "G-1 reviewer verified the source evidence"
    } | ConvertTo-Json
    $reviewedPassport = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/products/$($episode.product.id)/passports/product/review" -Method Post -Headers $headers -ContentType "application/json" -Body $reviewBody
    $reviewRetry = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/products/$($episode.product.id)/passports/product/review" -Method Post -Headers $headers -ContentType "application/json" -Body $reviewBody
    $reviewQueueAfter = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/passport-reviews" -Headers $headers
    if (
        $reviewQueue.Count -lt 3 -or
        $reviewedPassport.id -ne $reviewRetry.id -or
        $reviewedPassport.version -ne 2 -or
        -not $reviewedPassport.approved_by -or
        @($reviewQueueAfter | Where-Object { $_.product.id -eq $episode.product.id }).Count -ne 2
    ) {
        throw "Passport human review queue or idempotent decision smoke failed"
    }
    $result.passport_human_review = $true

    $offerExternalId = "G1-OFFER-" + [guid]::NewGuid().ToString("N")
    $offerBody = @{
        product_id = $product.id
        supplier_ref = "g1-supplier"
        platform = "1688"
        external_id = $offerExternalId
        source_url = "https://detail.1688.com/offer/$offerExternalId.html"
        title = "G-1 evidence-backed supplier offer"
        currency = "CNY"
        unit_price = 50
        source_to_cny_rate = 1
        min_order_quantity = 10
        weight_kg = 0.5
        length_cm = 30
        width_cm = 20
        height_cm = 10
        domestic_logistics_per_unit = 5
        evidence_ref = $evidenceRecord.id
        attributes = @{ verification = "G-1" }
        media = @()
    }
    $offer = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/sourcing/offers" -Method Post -Headers $headers -ContentType "application/json" -Body ($offerBody | ConvertTo-Json -Depth 5)
    $sameOffer = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/sourcing/offers" -Method Post -Headers $headers -ContentType "application/json" -Body ($offerBody | ConvertTo-Json -Depth 5)
    $changedOfferBody = $offerBody.Clone()
    $changedOfferBody.unit_price = 49
    $conflictStatus = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/sourcing/offers" -Method Post -Headers $headers -ContentType "application/json" -Body ($changedOfferBody | ConvertTo-Json -Depth 5)
    $scenarioBody = @{
        offer_id = $offer.id
        sale_price_rub = 1800
        rub_per_cny = 12
        international_freight_cny_per_kg = 30
        packaging_cny = 2
        warehousing_cny = 0
        tax_cny = 0
        last_mile_cny = 10
        fx_cost_cny = 0
        capital_cost_cny = 0
        aftersales_cny = 0
        loss_reserve_cny = 0
        customs_rate = 0.10
        platform_fee_rate = 0.10
        advertising_rate = 0.05
        return_reserve_rate = 0.10
        other_cost_cny = 0
        evidence = @($evidenceRecord.id)
        cost_evidence = @{
            product_cost = $evidenceRecord.id
            domestic_logistics = $evidenceRecord.id
            international_logistics = $evidenceRecord.id
            packaging = $evidenceRecord.id
            warehousing = $evidenceRecord.id
            customs = $evidenceRecord.id
            tax = $evidenceRecord.id
            last_mile = $evidenceRecord.id
            platform_fee = $evidenceRecord.id
            advertising = $evidenceRecord.id
            return = $evidenceRecord.id
            fx = $evidenceRecord.id
            capital_cost = $evidenceRecord.id
            aftersales = $evidenceRecord.id
            loss = $evidenceRecord.id
        }
        template_id = "ozon-ru-full-cost-v1"
        cost_states = @{
            product_cost = "estimate"
            domestic_logistics = "estimate"
            international_logistics = "estimate"
            packaging = "estimate"
            warehousing = "estimate"
            customs = "estimate"
            tax = "estimate"
            last_mile = "estimate"
            platform_fee = "estimate"
            advertising = "estimate"
            return = "estimate"
            fx = "estimate"
            capital_cost = "estimate"
            aftersales = "estimate"
            loss = "estimate"
        }
    }
    $scenario = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/sourcing/profit-scenarios" -Method Post -Headers $headers -ContentType "application/json" -Body ($scenarioBody | ConvertTo-Json -Depth 5)
    $profitTemplate = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/sourcing/profit-template" -Headers $headers
    $scenarioExplanation = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/sourcing/profit-scenarios/$($scenario.id)/explain" -Headers $headers
    $sourcingLineage = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/evidence/$($evidenceRecord.id)/lineage" -Headers $headers
    if (
        $offer.id -ne $sameOffer.id -or
        $conflictStatus -ne 422 -or
        [decimal]$scenario.cm3_cny -le 0 -or
        $profitTemplate.id -ne "ozon-ru-full-cost-v1" -or
        $profitTemplate.fields.Count -ne 15 -or
        $profitTemplate.automatic_pricing -ne $false -or
        $scenarioExplanation.release_ready -ne $true -or
        $scenarioExplanation.items.Count -ne 15 -or
        $scenarioExplanation.automatic_pricing -ne $false -or
        -not ($sourcingLineage | Where-Object { $_.to_type -eq "supplier_offer" -and $_.to_id -eq $offer.id }) -or
        -not ($sourcingLineage | Where-Object { $_.to_type -eq "profit_scenario" -and $_.to_id -eq $scenario.id })
    ) {
        throw "Sourcing immutable evidence gate smoke failed"
    }
    $result.sourcing_evidence_gate = $true
    $result.versioned_full_cost_template = $true

    $actualCostCatalog = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/finance/cost-authorities" -Headers $headers
    $pendingActualCost = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/finance/cost-evidence/$($evidenceRecord.id)/authority-review?cost_type=product_cost" -Headers $headers
    $selfActualCostReview = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/finance/cost-evidence/$($evidenceRecord.id)/authority-review" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        cost_type = "product_cost"
        authority_id = "supplier_invoice_payment"
        accepted = $true
        authentic_original = $true
        cost_scope_matches = $true
        charging_party_matches = $true
        amount_currency_period_matches = $true
        rationale = "Uploader self-review must fail"
    } | ConvertTo-Json)
    $actualCostReview = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/finance/cost-evidence/$($evidenceRecord.id)/authority-review" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body (@{
        cost_type = "product_cost"
        authority_id = "supplier_invoice_payment"
        accepted = $true
        authentic_original = $true
        cost_scope_matches = $true
        charging_party_matches = $true
        amount_currency_period_matches = $true
        rationale = "Independent G-1 review matched supplier invoice, payment, scope, party, currency and period"
    } | ConvertTo-Json)
    $actualScenarioBody = $scenarioBody.Clone()
    $actualCostStates = $scenarioBody.cost_states.Clone()
    $actualCostStates.product_cost = "actual"
    $actualScenarioBody.cost_states = $actualCostStates
    $actualScenario = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/sourcing/profit-scenarios" -Method Post -Headers $headers -ContentType "application/json" -Body ($actualScenarioBody | ConvertTo-Json -Depth 5)
    if (
        $actualCostCatalog.schema_version -ne "cost-actual-authority-v1" -or
        $actualCostCatalog.items.Count -ne 15 -or
        ($actualCostCatalog.items | Where-Object { $_.cost_type -eq "product_cost" }).authorities[0].id -ne "supplier_invoice_payment" -or
        $actualCostCatalog.automatic_state_change -ne $false -or
        $actualCostCatalog.automatic_finance_posting -ne $false -or
        $actualCostCatalog.automatic_procurement -ne $false -or
        $actualCostCatalog.automatic_listing -ne $false -or
        $pendingActualCost.status -ne "pending" -or
        $selfActualCostReview -ne 422 -or
        $actualCostReview.review.metadata.cost_type -ne "product_cost" -or
        $actualScenario.cost_states.product_cost -ne "actual" -or
        [decimal]$actualScenario.cm3_cny -le 0
    ) {
        throw "Actual cost authority and independent review smoke failed"
    }
    $result.actual_cost_authority_gate = $true
    $result.actual_cost_authority_catalog = $true

    $gateReadiness = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operations/readiness" -Headers $headers
    $gateProduct = $gateReadiness.products | Where-Object { $_.product.id -eq $product.id }
    $gateException = $gateReadiness.exception_workspace.items | Where-Object { $_.source_id -eq "SKU-003" }
    if (
        $gateReadiness.status -ne "needs_input" -or
        $gateReadiness.counts.bound_offers -ne 2 -or
        $gateProduct.supplier_count -ne 1 -or
        $gateProduct.offer_count -ne 1 -or
        $gateProduct.positive_profit_scenario_count -ne 1 -or
        -not ($gateReadiness.requirements | Where-Object { $_.id -eq "GOV-001" -and $_.ready }) -or
        -not ($gateReadiness.requirements | Where-Object { $_.id -eq "OZN-001" -and $_.ready }) -or
        -not ($gateReadiness.requirements | Where-Object { $_.id -eq "SKU-003" -and -not $_.ready })
    ) {
        Write-Host ($gateReadiness | ConvertTo-Json -Depth 12)
        throw "G0-G1 operating readiness projection smoke failed"
    }
    $result.operations_readiness = $true
    if (
        -not $gateReadiness.exception_workspace.advisory_only -or
        $gateReadiness.exception_workspace.automatic_resolution -ne $false -or
        $gateReadiness.exception_workspace.platform_write_allowed -ne $false -or
        -not $gateException -or
        $gateException.source_type -ne "gate_requirement" -or
        -not $gateException.owner_role -or
        -not $gateException.next_action
    ) {
        Write-Host ($gateReadiness.exception_workspace | ConvertTo-Json -Depth 12)
        throw "Evidence-backed exception workspace smoke failed"
    }
    $result.evidence_backed_exception_workspace = $true

    $passportBodies = @(
        @{
            kind = "product"
            facts = @{
                decision = "approved"
                material = "verification-material"
                intended_use = "G-1 verification only"
                country_of_origin = "CN"
                weight_kg = "0.5"
                dimensions_cm = @{ length = 30; width = 20; height = 10 }
            }
            evidence = @($evidenceRecord.id)
        },
        @{
            kind = "compliance"
            facts = @{
                decision = "approved"
                hs_code = "verification-only"
                eaeu_rules = @("verification-only")
                eac_requirement = "verification-only"
                chestny_znak_requirement = "verification-only"
                russian_labeling = "verification-only"
                ip_status = "verification-only"
                transport_restrictions = "verification-only"
                sellability = "verification-only"
            }
            evidence = @($evidenceRecord.id)
        },
        @{
            kind = "quality"
            facts = @{
                decision = "approved"
                golden_sample_ref = "g1://sample"
                inspection_plan = @("verification-only")
                packaging_test = "verification-only"
            }
            evidence = @($evidenceRecord.id)
        }
    )
    $passportIds = @()
    foreach ($passportBody in $passportBodies) {
        $passport = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/products/$($product.id)/passports" -Method Post -Headers $headers -ContentType "application/json" -Body ($passportBody | ConvertTo-Json -Depth 6)
        $passportIds += $passport.id
    }
    $validatedProduct = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/products/$($product.id)/validate" -Method Post -Headers $headers
    $validatedReadiness = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/products/$($product.id)/readiness" -Headers $headers
    $passportLineage = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/evidence/$($evidenceRecord.id)/lineage" -Headers $headers
    $linkedPassports = @($passportLineage | Where-Object { $_.to_type -eq "passport" -and $_.to_id -in $passportIds })
    if (
        $validatedProduct.status -ne "validated" -or
        -not $validatedReadiness.ready_for_validation -or
        @($validatedReadiness.passports | Where-Object { -not $_.evidence_valid }).Count -ne 0 -or
        $linkedPassports.Count -ne 3
    ) {
        throw "Passport immutable evidence gate smoke failed"
    }
    $result.passport_evidence_gate = $true

    $comparisonOffers = @(1..3 | ForEach-Object {
        @{
            supplier_ref = "g1-factory-$_"
            platform = "1688"
            external_id = "G1-COMPARE-$sku-$_"
            source_url = "https://example.com/g1-offer-$_"
            title = "G-1 comparison supplier $_"
            currency = "CNY"
            unit_price = 30 + $_
            source_to_cny_rate = 1
            min_order_quantity = 100
            weight_kg = 0.5
            length_cm = 30
            width_cm = 20
            height_cm = 10
            domestic_logistics_per_unit = 2
            attributes = @{}
            media = @()
        }
    })
    $comparisonProfitInputs = @{
        sale_price_rub = 1800
        rub_per_cny = 12
        international_freight_cny_per_kg = 30
        packaging_cny = 2
        last_mile_cny = 15
        customs_rate = 0.05
        platform_fee_rate = 0.15
        advertising_rate = 0.08
        return_reserve_rate = 0.04
        other_cost_cny = 0
    }
    $comparisonForm = @{
        product_id = $product.id
        effective_at = "2026-07-16T00:00:00+08:00"
        offers_json = $comparisonOffers | ConvertTo-Json -Depth 5 -Compress
        profit_inputs_json = $comparisonProfitInputs | ConvertTo-Json -Compress
        offer_evidence_1 = Get-Item $EpisodeSmokeFiles[0]
        offer_evidence_2 = Get-Item $EpisodeSmokeFiles[1]
        offer_evidence_3 = Get-Item $EpisodeSmokeFiles[2]
        assumption_evidence = Get-Item $EvidenceSmokeFile
    }
    $comparisonIntake = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/sourcing/comparison-intake" -Method Post -Headers $headers -Form $comparisonForm
    $comparisonRetry = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/sourcing/comparison-intake" -Method Post -Headers $headers -Form $comparisonForm
    $comparison = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/sourcing/comparisons/$($product.id)" -Headers $headers
    if (
        $comparisonIntake.offers.Count -ne 3 -or
        $comparisonRetry.scenarios[0].id -ne $comparisonIntake.scenarios[0].id -or
        $comparison.supplier_count -lt 3 -or
        -not $comparison.ready_for_procurement_review
    ) {
        throw "Three-supplier evidence comparison smoke failed"
    }
    $result.supplier_comparison_intake = $true

    $portfolioReadiness = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operations/readiness" -Headers $headers
    $portfolioRow = $portfolioReadiness.candidate_portfolio.rows | Where-Object { $_.product.id -eq $product.id }
    if (
        -not $portfolioReadiness.candidate_portfolio.advisory_only -or
        $portfolioReadiness.candidate_portfolio.automatic_product_selection -ne $false -or
        $portfolioReadiness.candidate_portfolio.automatic_procurement -ne $false -or
        $portfolioReadiness.candidate_portfolio.automatic_pricing -ne $false -or
        $portfolioReadiness.candidate_portfolio.automatic_listing -ne $false -or
        -not $portfolioRow -or
        -not $portfolioRow.ready_for_g1_review -or
        -not $portfolioRow.best_scenario.release_ready -or
        $portfolioRow.best_scenario.supplier_ref -notlike "g1-factory-*"
    ) {
        Write-Host ($portfolioReadiness.candidate_portfolio | ConvertTo-Json -Depth 12)
        throw "Qualified three-candidate portfolio smoke failed"
    }
    $result.three_candidate_portfolio = $true

    $selectedOffer = $comparisonIntake.offers[0]
    $selectedScenario = $comparisonIntake.scenarios[0]
    $procurementBody = @{
        product_id = $product.id
        offer_id = $selectedOffer.id
        scenario_id = $selectedScenario.id
        quantity = $selectedOffer.min_order_quantity
        rationale = "G-1 evidence-backed three-supplier comparison"
    } | ConvertTo-Json
    $procurementApproval = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/sourcing/procurement-candidates" -Method Post -Headers $headers -ContentType "application/json" -Body $procurementBody
    $selfApprovalStatus = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/approvals/$($procurementApproval.id)/decision" -Method Post -Headers $headers -ContentType "application/json" -Body (@{ approved = $true; reason = "self approval must fail" } | ConvertTo-Json)
    $approvedProcurement = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/approvals/$($procurementApproval.id)/decision" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body (@{ approved = $true; reason = "Independent G-1 approval" } | ConvertTo-Json)
    $approvalQueue = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/approvals" -Headers $headers
    if (
        $procurementApproval.status -ne "pending" -or
        $selfApprovalStatus -ne 422 -or
        $approvedProcurement.status -ne "approved" -or
        $approvedProcurement.decided_by -ne "g1-independent-approver" -or
        -not ($approvalQueue | Where-Object { $_.id -eq $procurementApproval.id })
    ) {
        throw "Procurement dual-control approval smoke failed"
    }
    $result.procurement_dual_control = $true

    $sampleOrder = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/procurement/sample-orders" -Method Post -Headers $headers -ContentType "application/json" -Body (@{ approval_id = $procurementApproval.id } | ConvertTo-Json)
    $sampleOrderRetry = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/procurement/sample-orders" -Method Post -Headers $headers -ContentType "application/json" -Body (@{ approval_id = $procurementApproval.id } | ConvertTo-Json)
    $sampleEvents = @(
        @{ type = "order_confirmed"; at = "2026-07-16T01:00:00+00:00"; facts = @{ supplier_order_ref = "G1-PO-1001"; promised_delivery_at = "2026-07-20T00:00:00+00:00" } },
        @{ type = "shipped"; at = "2026-07-17T00:00:00+00:00"; facts = @{ tracking_ref = "G1-TRACKING"; carrier = "G1 carrier" } },
        @{ type = "received"; at = "2026-07-19T00:00:00+00:00"; facts = @{ received_quantity = $selectedOffer.min_order_quantity; damaged_quantity = 0 } },
        @{ type = "inspection_completed"; at = "2026-07-19T01:00:00+00:00"; facts = @{ inspected_quantity = 10; passed_quantity = 10; defect_count = 0; result = "passed" } },
        @{ type = "golden_sample_approved"; at = "2026-07-19T02:00:00+00:00"; facts = @{ golden_sample_ref = "G1-GOLDEN-SAMPLE" } }
    )
    $sampleTimeline = $sampleOrder
    foreach ($sampleEvent in $sampleEvents) {
        $sampleTimeline = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/procurement/sample-orders/$($sampleOrder.id)/events" -Method Post -Headers $headers -Form @{
            event_type = $sampleEvent.type
            effective_at = $sampleEvent.at
            facts_json = $sampleEvent.facts | ConvertTo-Json -Compress
            file = Get-Item $EvidenceSmokeFile
        }
    }
    $sampleOrders = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/procurement/sample-orders" -Headers $headers
    if (
        $sampleOrder.id -ne $sampleOrderRetry.id -or
        $sampleTimeline.status -ne "golden_sample_approved" -or
        $sampleTimeline.events.Count -ne 5 -or
        -not ($sampleOrders | Where-Object { $_.id -eq $sampleOrder.id })
    ) {
        throw "Evidence-backed sample procurement lifecycle smoke failed"
    }
    $result.sample_procurement_lifecycle = $true

    $supplierPerformance = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/procurement/suppliers/performance" -Headers $headers
    $selectedPerformance = $supplierPerformance | Where-Object { $_.supplier_ref -eq $selectedOffer.supplier_ref }
    $backupOptions = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/procurement/sample-orders/$($sampleOrder.id)/backup-options" -Headers $headers
    if (
        $selectedPerformance.score -ne "100.0" -or
        $backupOptions.automatic_switch -ne $false -or
        $backupOptions.options.Count -lt 2
    ) {
        throw "Supplier performance or controlled backup recommendation smoke failed"
    }
    $result.supplier_performance_backup = $true

    $orderExternalId = "G1-ORDER-" + [guid]::NewGuid().ToString("N")
    @(
        "order_id;sku;quantity;currency;gross_revenue;effective_at"
        "$orderExternalId;$($product.sku);2;RUB;1299.50;2026-07-16T10:00:00+03:00"
    ) | Set-Content -LiteralPath $ImportSmokeFile -Encoding UTF8
    $import = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/imports/ozon" -Method Post -Headers $headers -Form @{
        file = Get-Item $ImportSmokeFile
        effective_at = "2026-07-16T10:00:00+03:00"
        report_period_start = "2026-07-01"
        report_period_end = "2026-07-31"
    }
    $promotion = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/imports/$($import.id)/promote" -Method Post -Headers $headers
    $formalFacts = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/facts?fact_type=ozon_order" -Headers $headers
    $promotedFact = $formalFacts | Where-Object natural_key -eq $orderExternalId
    $factLineage = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/evidence/$($import.evidence_id)/lineage" -Headers $headers
    if (
        $import.record_type -ne "ozon_order" -or
        $import.accepted_count -ne 1 -or
        -not $import.evidence_id -or
        $promotion.promoted_count -ne 1 -or
        $promotedFact.product_id -ne $product.id -or
        $promotedFact.resolution_status -ne "resolved" -or
        -not ($factLineage | Where-Object { $_.to_type -eq "commerce_fact" -and $_.to_id -eq $promotedFact.id })
    ) {
        $diagnostic = @{
            import = $import
            promotion = $promotion
            promoted_fact = $promotedFact
            lineage = $factLineage
        } | ConvertTo-Json -Depth 8 -Compress
        throw "Ozon staging-to-formal-fact promotion smoke failed: $diagnostic"
    }
    $result.formal_fact_promotion = $true

    @(
        "operation_id;fee_type;amount;currency;effective_at"
        "$orderExternalId;g1_service;99.5;RUB;2026-07-16T10:00:00+03:00"
    ) | Set-Content -LiteralPath $FeeImportSmokeFile -Encoding UTF8
    $feeImport = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/imports/ozon" -Method Post -Headers $headers -Form @{
        file = Get-Item $FeeImportSmokeFile
        effective_at = "2026-07-16T10:00:00+03:00"
        report_period_start = "2026-07-01"
        report_period_end = "2026-07-31"
    }
    $feePromotionBeforeReview = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/imports/$($feeImport.id)/promote" -Method Post -Headers $headers
    $feeReview = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/imports/$($feeImport.id)/finance-review" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body (@{
        accepted = $true
        authentic_account_export = $true
        period_matches = $true
        not_public_sample = $true
        complete_export = $true
        rationale = "Independent G-1 review of the accepted Ozon fee export"
    } | ConvertTo-Json)
    $feeCodesBefore = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/imports/$($feeImport.id)/fee-codes" -Headers $headers
    $feePromotionBeforeMapping = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/imports/$($feeImport.id)/promote" -Method Post -Headers $headers
    $feeMappingBody = @{
        provider = "ozon"
        raw_code = "g1_service"
        canonical_type = "platform_fee"
        sign_rule = "absolute_outflow"
        effective_from = "2026-07-01T00:00:00+00:00"
        evidence_id = $evidenceRecord.id
    } | ConvertTo-Json
    $genericOzonMappingStatus = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/finance/fee-mappings" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body $feeMappingBody
    $feeMappingApproval = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/imports/$($feeImport.id)/fee-mappings" -Method Post -Headers $approverHeaders -ContentType "application/json" -Body (@{
        raw_code = "g1_service"
        canonical_type = "platform_fee"
        sign_rule = "absolute_outflow"
        effective_from = "2026-07-01T00:00:00+00:00"
        rationale = "Approve the observed G-1 Ozon service code as a platform fee"
    } | ConvertTo-Json)
    $feeCodesAfter = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/imports/$($feeImport.id)/fee-codes" -Headers $headers
    $feePromotion = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/imports/$($feeImport.id)/promote" -Method Post -Headers $headers
    $formalFeeFacts = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/facts?fact_type=ozon_fee" -Headers $headers
    $promotedFeeFact = $formalFeeFacts | Where-Object natural_key -eq "$orderExternalId`:g1_service"
    $feeEntry = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/finance/facts/$($promotedFeeFact.id)/ingest" -Method Post -Headers $headers
    $fxBody = @{
        base_currency = "RUB"
        quote_currency = "CNY"
        rate = 0.08
        effective_at = "2026-07-01T00:00:00+00:00"
        source = "g1-fx"
        evidence_id = $evidenceRecord.id
    } | ConvertTo-Json
    $fxRate = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/finance/fx-rates" -Method Post -Headers $headers -ContentType "application/json" -Body $fxBody
    $orderEntry = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/finance/facts/$($promotedFact.id)/ingest" -Method Post -Headers $headers
    foreach ($entry in @(
        @{ entry_kind = "platform_settlement"; source_ref = "g1-settlement"; amount = 1200; evidence_id = $evidenceRecord.id },
        @{ entry_kind = "bank_receipt"; source_ref = "g1-bank"; amount = 1200; evidence_id = $bankEvidenceRecord.id }
    )) {
        $entryBody = @{
            entry_kind = $entry.entry_kind
            source = "g1_verification"
            source_ref = "$($entry.source_ref)-$orderExternalId"
            reconciliation_key = $orderExternalId
            amount = $entry.amount
            currency = "RUB"
            effective_at = "2026-07-16T10:00:00+03:00"
            evidence_id = $entry.evidence_id
        }
        Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/finance/entries" -Method Post -Headers $headers -ContentType "application/json" -Body ($entryBody | ConvertTo-Json) | Out-Null
    }
    $reconciliation = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/finance/reconciliations/$orderExternalId" -Method Post -Headers $financeReviewerHeaders -ContentType "application/json" -Body (@{
        quote_currency = "CNY"
        fx_source = "g1-fx"
        tolerance_ratio = 0.003
    } | ConvertTo-Json)
    if (
        $feeImport.record_type -ne "ozon_fee" -or
        $feePromotionBeforeReview -ne 422 -or
        $feeReview.review.metadata.decision -ne "accepted" -or
        $feeCodesBefore.ready -ne $false -or
        $feePromotionBeforeMapping -ne 422 -or
        $genericOzonMappingStatus -ne 422 -or
        $feeMappingApproval.mapping.raw_code -ne "g1_service" -or
        $feeMappingApproval.approval.source -ne "ozon_fee_mapping_approval" -or
        $feeCodesAfter.ready -ne $true -or
        $feePromotion.promoted_count -ne 1 -or
        $feeEntry.entry_kind -ne "platform_fee" -or
        $fxRate.base_currency -ne "RUB" -or
        $orderEntry.entry_kind -ne "order_receivable" -or
        $reconciliation.status -ne "matched" -or
        $reconciliation.snapshot.unknown_fees.Count -ne 0 -or
        $reconciliation.snapshot.evidence_conflicts.Count -ne 0 -or
        $reconciliation.snapshot.self_review_dependencies.Count -ne 0
    ) {
        $diagnostic = @{
            fee_import = $feeImport
            promotion_before_review = $feePromotionBeforeReview
            fee_review = $feeReview
            codes_before = $feeCodesBefore
            promotion_before_mapping = $feePromotionBeforeMapping
            generic_mapping_status = $genericOzonMappingStatus
            mapping_approval = $feeMappingApproval
            codes_after = $feeCodesAfter
            fee_promotion = $feePromotion
            promoted_fee_fact = $promotedFeeFact
            fee_entry = $feeEntry
            fx_rate = $fxRate
            order_entry = $orderEntry
            reconciliation = $reconciliation
        } | ConvertTo-Json -Depth 8 -Compress
        throw "Evidence-backed finance reconciliation smoke failed: $diagnostic"
    }
    $result.finance_fee_mapping_gate = $true
    $result.finance_reconciliation = $true

    $cashPlan = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/finance/cash-plan" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        source = "g1_verification"
        source_ref = "g1-cash-$orderExternalId"
        category = "inventory"
        amount = -100
        currency = "RUB"
        expected_at = "2026-07-17T00:00:00+00:00"
        probability = 1
        status = "committed"
        evidence_id = $evidenceRecord.id
    } | ConvertTo-Json)
    $cashForecast = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/finance/cash-forecast?start_at=2026-07-16T00%3A00%3A00%2B00%3A00&opening_balance=100&fx_source=g1-fx&quote_currency=CNY" -Headers $headers
    if ($cashPlan.status -ne "committed" -or $cashForecast.status -ne "ready" -or $cashForecast.weeks.Count -ne 13) {
        throw "13-week cash forecast smoke failed"
    }
    $result.cash_forecast = $true

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
        -not $healthLoop.evidence_integrity.completed -or
        $healthLoop.evidence_integrity.pages -lt 1 -or
        $healthLoop.evidence_integrity.invalid -ne 0
    ) {
        throw (
            "24x7 Evidence integrity health-loop smoke failed: " +
            "control_plane=$($healthLoop.control_plane.ok) " +
            "readiness=$($healthLoop.operations_readiness.ok) " +
            "integrity=$($healthLoop.evidence_integrity.ok) " +
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
        -WorkingDirectory $Web -WindowStyle Hidden -PassThru `
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
    if ($WebContainer) {
        docker rm --force $WebContainer 2>$null | Out-Null
    }
    Stop-OwnedProcess $WebProcess
    Stop-OwnedProcess $ApiProcess
    Stop-OwnedListener $WebProcess $WebPort
    Stop-OwnedListener $ApiProcess $ApiPort
    Stop-SmokeProcesses
    $remainingListeners = Get-NetTCPConnection -LocalPort $ApiPort, $WebPort -State Listen -ErrorAction SilentlyContinue
    $result.cleanup_processes = $null -eq $remainingListeners
    if ($PostgresContainer) {
        docker exec $PostgresContainer dropdb --if-exists --force -U hermes $DatabaseName 2>$null | Out-Null
        docker exec $PostgresContainer dropdb --if-exists --force -U hermes $RestoreDatabaseName 2>$null | Out-Null
        $remainingDatabase = docker exec $PostgresContainer psql -U hermes -d postgres -Atc "SELECT datname FROM pg_database WHERE datname IN ('$DatabaseName','$RestoreDatabaseName');" 2>$null
        $result.cleanup_database = $LASTEXITCODE -eq 0 -and -not $remainingDatabase
    } elseif ($UseExistingPostgres) {
        try {
            & $Python "scripts/manage_g1_database.py" "drop" | Out-Null
            $result.cleanup_database = $LASTEXITCODE -eq 0
        } catch {
            $result.cleanup_database = $false
        }
    }
    if (Test-Path $WebSmoke) {
        $resolvedRuntime = [IO.Path]::GetFullPath($Runtime).TrimEnd("\") + "\"
        $resolvedSmoke = [IO.Path]::GetFullPath($WebSmoke)
        if ($resolvedSmoke.StartsWith($resolvedRuntime, [StringComparison]::OrdinalIgnoreCase)) {
            $nodeModulesJunction = Join-Path $WebSmoke "node_modules"
            if (Test-Path $nodeModulesJunction) {
                [IO.Directory]::Delete($nodeModulesJunction, $false)
            }
            if (Test-Path $WebSmoke) {
                for ($attempt = 1; $attempt -le 16 -and (Test-Path $WebSmoke); $attempt++) {
                    try {
                        [IO.Directory]::Delete($resolvedSmoke, $true)
                    } catch {
                        $result.cleanup_file_errors += $_.Exception.Message
                        Start-Sleep -Milliseconds 500
                    }
                }
            }
        }
    }
    if (Test-Path $PytestTemp) {
        $resolvedRuntime = [IO.Path]::GetFullPath($Runtime).TrimEnd("\") + "\"
        $resolvedPytestTemp = [IO.Path]::GetFullPath($PytestTemp)
        if ($resolvedPytestTemp.StartsWith($resolvedRuntime, [StringComparison]::OrdinalIgnoreCase)) {
            [IO.Directory]::Delete($resolvedPytestTemp, $true)
        }
    }
    if (Test-Path $BackupSmokeDirectory) {
        $resolvedRuntime = [IO.Path]::GetFullPath($Runtime).TrimEnd("\") + "\"
        $resolvedBackup = [IO.Path]::GetFullPath($BackupSmokeDirectory)
        if ($resolvedBackup.StartsWith($resolvedRuntime, [StringComparison]::OrdinalIgnoreCase)) {
            [IO.Directory]::Delete($resolvedBackup, $true)
        }
    }
    Remove-Item -LiteralPath $EvidenceSmokeFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $BankEvidenceSmokeFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $PilotResponseSmokeFile -Force -ErrorAction SilentlyContinue
    $EpisodeSmokeFiles | ForEach-Object { Remove-Item -LiteralPath $_ -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $ImportSmokeFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $FeeImportSmokeFile -Force -ErrorAction SilentlyContinue
    $result.cleanup_files =
        -not (Test-Path $WebSmoke) -and
        -not (Test-Path $PytestTemp) -and
        -not (Test-Path $BackupSmokeDirectory) -and
        -not (Test-Path $EvidenceSmokeFile) -and
        -not (Test-Path $BankEvidenceSmokeFile) -and
        -not (Test-Path $PilotResponseSmokeFile) -and
        -not ($EpisodeSmokeFiles | Where-Object { Test-Path $_ }) -and
        -not (Test-Path $ImportSmokeFile) -and
        -not (Test-Path $FeeImportSmokeFile)
    if ($result.status -eq "PASS" -and -not ($result.cleanup_processes -and $result.cleanup_database -and $result.cleanup_files)) {
        $result.status = "FAIL"
        $result.cleanup_error = "Disposable verification resources were not fully removed"
    }
    $result.finished_at = (Get-Date).ToUniversalTime().ToString("o")
    $result | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $Runtime "G1_VERIFICATION.json")
    Write-Output ($result | ConvertTo-Json -Depth 5)
}
