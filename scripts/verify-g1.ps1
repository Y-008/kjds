$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Runtime = Join-Path $Root ".runtime"
$Web = Join-Path $Root "web"
$WebSmoke = Join-Path $Runtime ("web-g1-" + [guid]::NewGuid().ToString("N"))
$DatabaseName = "kjds_g1_smoke"
$ApiPort = 8010
$WebPort = 3010
$EvidenceSmokeFile = Join-Path $Runtime ("g1-evidence-" + [guid]::NewGuid().ToString("N") + ".txt")
$EpisodeSmokeFiles = @(
    Join-Path $Runtime ("g1-product-evidence-" + [guid]::NewGuid().ToString("N") + ".txt")
    Join-Path $Runtime ("g1-compliance-evidence-" + [guid]::NewGuid().ToString("N") + ".txt")
    Join-Path $Runtime ("g1-quality-evidence-" + [guid]::NewGuid().ToString("N") + ".txt")
)
$ImportSmokeFile = Join-Path $Runtime ("g1-orders-" + [guid]::NewGuid().ToString("N") + ".csv")
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
    api_auth = $false
    kill_switch = $false
    api_database_write = $false
    evidence_ledger = $false
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
    finance_reconciliation = $false
    cash_forecast = $false
    web_health = $false
    web_proxy_auth = $false
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
    $env:KJDS_LIMITED_EXECUTION_ENABLED = "true"
    $env:KJDS_API_KEY = "g1-smoke-" + [guid]::NewGuid().ToString("N")
    $ApproverApiKey = "g1-approver-" + [guid]::NewGuid().ToString("N")
    $KnowledgeApiKey = "g1-knowledge-" + [guid]::NewGuid().ToString("N")
    $ExecutorApiKey = "g1-executor-" + [guid]::NewGuid().ToString("N")
    $env:KJDS_API_ACTOR = "g1-verifier"
    $env:KJDS_API_ROLES = "operator,reviewer,approver,risk,admin"
    $ApiCredentials = @{}
    $ApiCredentials[$env:KJDS_API_KEY] = @{ actor = "g1-verifier"; roles = @("operator", "reviewer", "admin") }
    $ApiCredentials[$ApproverApiKey] = @{ actor = "g1-independent-approver"; roles = @("reviewer", "approver") }
    $ApiCredentials[$KnowledgeApiKey] = @{ actor = "g1-knowledge-publisher"; roles = @("approver") }
    $ApiCredentials[$ExecutorApiKey] = @{ actor = "g1-ozon-worker"; roles = @("executor") }
    $env:KJDS_API_KEYS_JSON = $ApiCredentials | ConvertTo-Json -Compress

    Invoke-External -Command uv -Arguments @("run", "python", "-m", "alembic", "upgrade", "head")
    $current = (uv run python -m alembic current).Trim()
    if ($LASTEXITCODE -ne 0 -or $current -notmatch "20260717_0020.*head") {
        throw "Unexpected migration head: $current"
    }
    $result.migration = "20260717_0020"

    Invoke-External -Command uv -Arguments @("run", "python", "-m", "alembic", "downgrade", "20260717_0019")
    $downgraded = (uv run python -m alembic current).Trim()
    if ($LASTEXITCODE -ne 0 -or $downgraded -notmatch "20260717_0019") {
        throw "Migration downgrade verification failed: $downgraded"
    }
    Invoke-External -Command uv -Arguments @("run", "python", "-m", "alembic", "upgrade", "head")
    $result.migration_replay = $true

    Write-Output "[G-1] Running Python quality gates"
    $pythonFiles = @(
        git ls-files -- "*.py"
        Get-ChildItem (Join-Path $Root "migrations\versions") -Filter "*.py" -File |
            ForEach-Object { $_.FullName.Substring($Root.Length + 1) }
    ) | Sort-Object -Unique
    Invoke-External -Command uv -Arguments (@("run", "ruff", "check") + $pythonFiles)
    $result.lint = $true
    $testFiles = @(git ls-files -- "tests/test_*.py")
    Invoke-External -Command uv -Arguments (@("run", "python", "-m", "pytest", "-q") + $testFiles)
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
    if ($health.status -ne "ok" -or $health.database.status -ne "ok" -or -not $health.security.api_identity_configured) {
        throw "API health did not confirm PostgreSQL readiness"
    }
    $result.api_health = $true

    $sku = "G1-SMOKE-" + (Get-Date -Format "yyyyMMddHHmmss")
    $body = @{ sku = $sku; name = "Disposable G-1 smoke product" } | ConvertTo-Json
    $headers = @{ "X-KJDS-API-Key" = $env:KJDS_API_KEY }
    $approverHeaders = @{ "X-KJDS-API-Key" = $ApproverApiKey }
    $knowledgeHeaders = @{ "X-KJDS-API-Key" = $KnowledgeApiKey }
    $executorHeaders = @{ "X-KJDS-API-Key" = $ExecutorApiKey }
    $unauthorized = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/products"
    $invalid = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/products" -Headers @{ "X-KJDS-API-Key" = "invalid" }
    $authorized = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/products" -Headers $headers
    if ($unauthorized -ne 401 -or $invalid -ne 403 -or $authorized -ne 200) {
        throw "API authentication smoke failed"
    }
    $result.api_auth = $true

    $switchBody = @{ reason = "G-1 kill switch exercise" } | ConvertTo-Json
    $engaged = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/system/kill-switch/engage" -Method Post -Headers $headers -ContentType "application/json" -Body $switchBody
    $blocked = Get-HttpStatus "http://127.0.0.1:$ApiPort/v1/products" -Method Post -Headers $headers -ContentType "application/json" -Body $body
    $released = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/system/kill-switch/release" -Method Post -Headers $headers -ContentType "application/json" -Body (@{ reason = "G-1 exercise completed" } | ConvertTo-Json)
    if (-not $engaged.engaged -or $blocked -ne 423 -or $released.engaged) {
        throw "Kill switch smoke failed"
    }
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
    $lineage = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/evidence/$($evidenceRecord.id)/lineage" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        target_type = "product"
        target_id = $product.id
        relationship = "supports"
    } | ConvertTo-Json)
    if (-not $verification.valid -or $lineage.to_id -ne $product.id) {
        throw "Immutable evidence and lineage smoke failed"
    }
    $result.evidence_ledger = $true

    $profiles = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/interaction-profiles" -Headers $headers
    $decisionProfile = $profiles | Where-Object { $_.id -eq "decision_review" }
    if (
        $profiles.Count -ne 5 -or
        "/x10think" -notin $decisionProfile.aliases -or
        "/oda" -notin $decisionProfile.aliases -or
        $decisionProfile.version -ne "1.0.0"
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
        adapter_id = "ozon.listing.draft.v1"
        target = @{ listing_id = "g1-ozon-listing" }
        precondition_state_hash = $executionStateHash
        intended_patch = @{ title = "G-1 validated candidate title" }
        rollback_patch = @{ title = "G-1 current title" }
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
    $claimedCommand = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/limited-execution-commands/$($limitedCommand.id)/claim" -Method Post -Headers $executorHeaders -ContentType "application/json" -Body (@{
        current_state_hash = $executionStateHash
        lease_seconds = 120
    } | ConvertTo-Json)
    $resultingExecutionHash = "b" * 64
    $executionReceipt = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/limited-execution-commands/$($limitedCommand.id)/receipt" -Method Post -Headers $executorHeaders -ContentType "application/json" -Body (@{
        outcome = "succeeded"
        remote_operation_id = "g1-simulated-ozon-operation"
        resulting_state_hash = $resultingExecutionHash
        mutation_applied = $true
        error_code = $null
        error_detail = $null
        evidence_ids = @($evidenceRecord.id)
    } | ConvertTo-Json -Depth 4)
    $rollbackCommand = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/limited-execution-commands/$($limitedCommand.id)/rollback" -Method Post -Headers $headers
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
        $executionPlan.live_execution_supported -eq $false -and
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
    $result.compensating_rollback = (
        $rollbackCommand.command_kind -eq "rollback" -and
        $rollbackCommand.expected_state_hash -eq $resultingExecutionHash -and
        $claimedRollback.status -eq "claimed" -and
        $rollbackReceipt.outcome -eq "succeeded"
    )
    if (
        -not $result.limited_execution_command -or
        -not $result.limited_execution_receipt -or
        -not $result.compensating_rollback
    ) {
        throw "Limited execution command, receipt, and rollback smoke failed"
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
        last_mile_cny = 10
        customs_rate = 0.10
        platform_fee_rate = 0.10
        advertising_rate = 0.05
        return_reserve_rate = 0.10
        other_cost_cny = 0
        evidence = @($evidenceRecord.id)
    }
    $scenario = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/sourcing/profit-scenarios" -Method Post -Headers $headers -ContentType "application/json" -Body ($scenarioBody | ConvertTo-Json -Depth 5)
    $sourcingLineage = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/evidence/$($evidenceRecord.id)/lineage" -Headers $headers
    if (
        $offer.id -ne $sameOffer.id -or
        $conflictStatus -ne 422 -or
        [decimal]$scenario.cm3_cny -le 0 -or
        -not ($sourcingLineage | Where-Object { $_.to_type -eq "supplier_offer" -and $_.to_id -eq $offer.id }) -or
        -not ($sourcingLineage | Where-Object { $_.to_type -eq "profit_scenario" -and $_.to_id -eq $scenario.id })
    ) {
        throw "Sourcing immutable evidence gate smoke failed"
    }
    $result.sourcing_evidence_gate = $true

    $gateReadiness = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/operations/readiness" -Headers $headers
    $gateProduct = $gateReadiness.products | Where-Object { $_.product.id -eq $product.id }
    if (
        $gateReadiness.status -ne "needs_input" -or
        $gateReadiness.counts.bound_offers -ne 1 -or
        $gateProduct.supplier_count -ne 1 -or
        $gateProduct.offer_count -ne 1 -or
        $gateProduct.positive_profit_scenario_count -ne 1 -or
        -not ($gateReadiness.requirements | Where-Object { $_.id -eq "GOV-001" -and $_.ready }) -or
        -not ($gateReadiness.requirements | Where-Object { $_.id -eq "OZN-001" -and $_.ready }) -or
        -not ($gateReadiness.requirements | Where-Object { $_.id -eq "SKU-003" -and -not $_.ready })
    ) {
        throw "G0-G1 operating readiness projection smoke failed"
    }
    $result.operations_readiness = $true

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
        "$orderExternalId;$sku;2;RUB;1299.50;2026-07-16T10:00:00+03:00"
    ) | Set-Content -LiteralPath $ImportSmokeFile -Encoding UTF8
    $import = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/imports/ozon" -Method Post -Headers $headers -Form @{
        file = Get-Item $ImportSmokeFile
        effective_at = "2026-07-16T10:00:00+03:00"
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

    $feeMappingBody = @{
        provider = "ozon"
        raw_code = "g1_service"
        canonical_type = "platform_fee"
        sign_rule = "absolute_outflow"
        effective_from = "2026-07-01T00:00:00+00:00"
        evidence_id = $evidenceRecord.id
    } | ConvertTo-Json
    $feeMapping = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/finance/fee-mappings" -Method Post -Headers $headers -ContentType "application/json" -Body $feeMappingBody
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
        @{ entry_kind = "platform_fee"; source_ref = "g1-fee"; raw_fee_code = "g1_service"; amount = 99.5 },
        @{ entry_kind = "platform_settlement"; source_ref = "g1-settlement"; amount = 1200 },
        @{ entry_kind = "bank_receipt"; source_ref = "g1-bank"; amount = 1200 }
    )) {
        $entryBody = @{
            entry_kind = $entry.entry_kind
            source = "g1_verification"
            source_ref = "$($entry.source_ref)-$orderExternalId"
            reconciliation_key = $orderExternalId
            amount = $entry.amount
            currency = "RUB"
            effective_at = "2026-07-16T10:00:00+03:00"
            evidence_id = $evidenceRecord.id
        }
        if ($entry.raw_fee_code) { $entryBody.raw_fee_code = $entry.raw_fee_code }
        Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/finance/entries" -Method Post -Headers $headers -ContentType "application/json" -Body ($entryBody | ConvertTo-Json) | Out-Null
    }
    $reconciliation = Invoke-RestMethod "http://127.0.0.1:$ApiPort/v1/finance/reconciliations/$orderExternalId" -Method Post -Headers $headers -ContentType "application/json" -Body (@{
        quote_currency = "CNY"
        fx_source = "g1-fx"
        tolerance_ratio = 0.003
    } | ConvertTo-Json)
    if (
        $feeMapping.raw_code -ne "g1_service" -or
        $fxRate.base_currency -ne "RUB" -or
        $orderEntry.entry_kind -ne "order_receivable" -or
        $reconciliation.status -ne "matched" -or
        $reconciliation.snapshot.unknown_fees.Count -ne 0
    ) {
        throw "Evidence-backed finance reconciliation smoke failed"
    }
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
            $nodeModulesJunction = Join-Path $WebSmoke "node_modules"
            if (Test-Path $nodeModulesJunction) {
                [IO.Directory]::Delete($nodeModulesJunction, $false)
            }
            if (Test-Path $WebSmoke) {
                Remove-Item -LiteralPath $WebSmoke -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Remove-Item -LiteralPath $EvidenceSmokeFile -Force -ErrorAction SilentlyContinue
    $EpisodeSmokeFiles | ForEach-Object { Remove-Item -LiteralPath $_ -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $ImportSmokeFile -Force -ErrorAction SilentlyContinue
    $result.cleanup_files =
        -not (Test-Path $WebSmoke) -and
        -not (Test-Path $EvidenceSmokeFile) -and
        -not ($EpisodeSmokeFiles | Where-Object { Test-Path $_ }) -and
        -not (Test-Path $ImportSmokeFile)
    if ($result.status -eq "PASS" -and -not ($result.cleanup_processes -and $result.cleanup_database -and $result.cleanup_files)) {
        $result.status = "FAIL"
        $result.cleanup_error = "Disposable verification resources were not fully removed"
    }
    $result.finished_at = (Get-Date).ToUniversalTime().ToString("o")
    $result | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $Runtime "G1_VERIFICATION.json")
    Write-Output ($result | ConvertTo-Json -Depth 5)
}
