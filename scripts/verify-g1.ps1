$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Runtime = Join-Path $Root ".runtime"
$Web = Join-Path $Root "web"
$WebSmoke = Join-Path $Runtime ("web-g1-" + [guid]::NewGuid().ToString("N"))
$DatabaseName = "kjds_g1_smoke"
$ApiPort = 8010
$WebPort = 3010
$EvidenceSmokeFile = Join-Path $Runtime ("g1-evidence-" + [guid]::NewGuid().ToString("N") + ".txt")
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
    $env:KJDS_API_KEY = "g1-smoke-" + [guid]::NewGuid().ToString("N")
    $env:KJDS_API_ACTOR = "g1-verifier"
    $env:KJDS_API_ROLES = "operator,reviewer,approver,risk,admin"

    Invoke-External -Command uv -Arguments @("run", "python", "-m", "alembic", "upgrade", "head")
    $current = (uv run python -m alembic current).Trim()
    if ($LASTEXITCODE -ne 0 -or $current -notmatch "20260716_0007.*head") {
        throw "Unexpected migration head: $current"
    }
    $result.migration = "20260716_0007"

    Invoke-External -Command uv -Arguments @("run", "python", "-m", "alembic", "downgrade", "20260716_0006")
    $downgraded = (uv run python -m alembic current).Trim()
    if ($LASTEXITCODE -ne 0 -or $downgraded -notmatch "20260716_0006") {
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
    if ($health.status -ne "ok" -or $health.database.status -ne "ok" -or -not $health.security.api_identity_configured) {
        throw "API health did not confirm PostgreSQL readiness"
    }
    $result.api_health = $true

    $sku = "G1-SMOKE-" + (Get-Date -Format "yyyyMMddHHmmss")
    $body = @{ sku = $sku; name = "Disposable G-1 smoke product" } | ConvertTo-Json
    $headers = @{ "X-KJDS-API-Key" = $env:KJDS_API_KEY }
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
    Remove-Item -LiteralPath $ImportSmokeFile -Force -ErrorAction SilentlyContinue
    $result.cleanup_files =
        -not (Test-Path $WebSmoke) -and
        -not (Test-Path $EvidenceSmokeFile) -and
        -not (Test-Path $ImportSmokeFile)
    if ($result.status -eq "PASS" -and -not ($result.cleanup_processes -and $result.cleanup_database -and $result.cleanup_files)) {
        $result.status = "FAIL"
        $result.cleanup_error = "Disposable verification resources were not fully removed"
    }
    $result.finished_at = (Get-Date).ToUniversalTime().ToString("o")
    $result | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $Runtime "G1_VERIFICATION.json")
    Write-Output ($result | ConvertTo-Json -Depth 5)
}
