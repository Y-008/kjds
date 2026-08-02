param([switch]$ControlPlaneOnly)

$ErrorActionPreference = "Continue"

function Test-HttpEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [int]$TimeoutSec = 4,
        [hashtable]$Headers = @{}
    )
    try {
        $response = Invoke-WebRequest -Uri $Uri -Headers $Headers -UseBasicParsing -TimeoutSec $TimeoutSec
        return [ordered]@{ ok = $true; status = $response.StatusCode; error = $null }
    }
    catch {
        return [ordered]@{ ok = $false; status = $null; error = $_.Exception.Message }
    }
}

function Invoke-JsonEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [ValidateSet("GET", "POST")][string]$Method = "GET",
        [int]$TimeoutSec = 15,
        [hashtable]$Headers = @{}
    )
    try {
        $response = Invoke-WebRequest `
            -Uri $Uri `
            -Method $Method `
            -Headers $Headers `
            -UseBasicParsing `
            -TimeoutSec $TimeoutSec
        $data = if ($response.Content) { $response.Content | ConvertFrom-Json } else { $null }
        return [ordered]@{ ok = $true; status = $response.StatusCode; data = $data; error = $null }
    }
    catch {
        return [ordered]@{ ok = $false; status = $null; data = $null; error = $_.Exception.Message }
    }
}

function Get-Setting([string]$Name, [string]$Default = "") {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ($value) { return $value }
    $root = Split-Path -Parent $PSScriptRoot
    $envFile = Join-Path $root ".env"
    if (Test-Path -LiteralPath $envFile) {
        $line = Get-Content -LiteralPath $envFile | Where-Object {
            $_ -match "^$([regex]::Escape($Name))="
        } | Select-Object -First 1
        if ($line) { return ($line -split "=", 2)[1].Trim() }
    }
    return $Default
}

function Get-BoundedIntegerSetting {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$Default,
        [Parameter(Mandatory = $true)][int]$Minimum,
        [Parameter(Mandatory = $true)][int]$Maximum
    )
    $raw = Get-Setting $Name "$Default"
    $parsed = 0
    if (-not [int]::TryParse($raw, [ref]$parsed) -or $parsed -lt $Minimum -or $parsed -gt $Maximum) {
        return [ordered]@{
            ok = $false
            value = $Default
            error = "$Name must be an integer between $Minimum and $Maximum"
        }
    }
    return [ordered]@{ ok = $true; value = $parsed; error = $null }
}

function Test-MonitorIdentityConfiguration {
    param(
        [string]$ApiKey,
        [string]$CredentialJson,
        [string[]]$DisallowedKeys = @()
    )
    if (-not $ApiKey) {
        return [ordered]@{ ok = $false; actor = $null; error = "KJDS_MONITOR_API_KEY is not configured" }
    }
    if ($DisallowedKeys | Where-Object { $_ -and $_ -ceq $ApiKey }) {
        return [ordered]@{ ok = $false; actor = $null; error = "Monitor credential must not reuse another runtime credential" }
    }
    if (-not $CredentialJson) {
        return [ordered]@{ ok = $false; actor = $null; error = "KJDS_API_KEYS_JSON is required for monitor identity validation" }
    }
    try {
        $mapping = $CredentialJson | ConvertFrom-Json
        $property = $mapping.PSObject.Properties | Where-Object { $_.Name -ceq $ApiKey } | Select-Object -First 1
        if (-not $property) {
            return [ordered]@{ ok = $false; error = "Monitor credential is not registered in KJDS_API_KEYS_JSON" }
        }
        $roles = @($property.Value.roles)
        if (-not $property.Value.actor -or $roles.Count -ne 1 -or $roles[0] -cne "monitor") {
            return [ordered]@{ ok = $false; actor = $null; error = "Monitor credential must map to exactly the monitor role" }
        }
        return [ordered]@{ ok = $true; actor = [string]$property.Value.actor; error = $null }
    }
    catch {
        return [ordered]@{ ok = $false; actor = $null; error = "KJDS_API_KEYS_JSON is not valid JSON" }
    }
}

function Invoke-BoundedSnapshot {
    param(
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [int]$TimeoutSeconds = 20
    )

    if (-not (Test-Path -LiteralPath $ScriptPath)) {
        return [ordered]@{ ok = $false; error = "snapshot script not found: $ScriptPath" }
    }
    $job = Start-Job -ArgumentList $ScriptPath -ScriptBlock {
        param($Path)
        & $Path | Out-Null
        [pscustomobject]@{ exit_code = if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE } }
    }
    try {
        $completed = Wait-Job -Job $job -Timeout $TimeoutSeconds
        if (-not $completed) {
            Stop-Job -Job $job -ErrorAction SilentlyContinue
            return [ordered]@{ ok = $false; error = "snapshot timed out after ${TimeoutSeconds}s" }
        }
        $payload = Receive-Job -Job $job -ErrorAction SilentlyContinue | Select-Object -Last 1
        if ($payload -and $payload.exit_code -eq 0) {
            return [ordered]@{ ok = $true; error = $null }
        }
        $exitCode = if ($payload) { $payload.exit_code } else { "unknown" }
        return [ordered]@{ ok = $false; error = "snapshot exited with code $exitCode" }
    }
    finally {
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }
}

function Invoke-EvidenceIntegritySweep {
    param(
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [string]$ApiKey,
        [int]$PageSize = 500,
        [int]$MaxPages = 20
    )
    if (-not $ApiKey) {
        return [ordered]@{
            ok = $false
            skipped = $true
            error = "skipped: KJDS_MONITOR_API_KEY is not configured"
            pages = 0
            scanned = 0
            invalid = 0
            incident_count = 0
            last_scan_evidence_id = $null
            completed = $false
        }
    }
    if ($PageSize -lt 1 -or $PageSize -gt 1000 -or $MaxPages -lt 1 -or $MaxPages -gt 1000) {
        return [ordered]@{
            ok = $false
            skipped = $false
            error = "Evidence integrity pagination settings are outside their safe bounds"
            pages = 0
            scanned = 0
            invalid = 0
            incident_count = 0
            last_scan_evidence_id = $null
            completed = $false
        }
    }

    $offset = 0
    $pages = 0
    $scanned = 0
    $invalid = 0
    $incidentCount = 0
    $lastScanEvidenceId = $null
    $completed = $false
    $errorMessage = $null
    while ($pages -lt $MaxPages) {
        $uri = "$BaseUrl/v1/evidence/integrity-scan?limit=$PageSize&offset=$offset"
        $call = Invoke-JsonEndpoint -Uri $uri -Method POST -Headers @{
            "X-KJDS-API-Key" = $ApiKey
        }
        if (-not $call.ok) {
            $errorMessage = $call.error
            break
        }
        $pages += 1
        $scanned += [int]$call.data.scanned
        $invalid += [int]$call.data.invalid
        if ($call.data.incident_ids) {
            $incidentCount += @($call.data.incident_ids.PSObject.Properties).Count
        }
        $lastScanEvidenceId = $call.data.scan_evidence_id
        if ($null -eq $call.data.next_offset) {
            $completed = $true
            break
        }
        $offset = [int]$call.data.next_offset
    }
    if (-not $completed -and -not $errorMessage) {
        $errorMessage = "Evidence integrity sweep exceeded the configured page limit"
    }
    if ($completed -and $invalid -gt 0) {
        $errorMessage = "Evidence integrity sweep found $invalid invalid record(s)"
    }
    return [ordered]@{
        ok = $completed -and $invalid -eq 0
        skipped = $false
        error = $errorMessage
        pages = $pages
        scanned = $scanned
        invalid = $invalid
        incident_count = $incidentCount
        last_scan_evidence_id = $lastScanEvidenceId
        completed = $completed
    }
}

function Invoke-AgentGateObservation {
    param(
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [string]$ApiKey,
        [string]$MonitorActorId
    )
    if (-not $ApiKey) {
        return [ordered]@{
            ok = $false
            skipped = $true
            error = "skipped: KJDS_MONITOR_API_KEY is not configured"
            project_id = "kjds-059-bas123"
            database_revision = $null
            observation_bucket = $null
            operating_subject_actor_id = $null
            subject_binding_sha256 = $null
            result_sha256 = $null
            states = $null
            counts = $null
        }
    }
    $uri = (
        "$BaseUrl/v1/agent-control/projects/" +
        "kjds-059-bas123/observe?store_ref=ozon-primary"
    )
    $call = Invoke-JsonEndpoint -Uri $uri -Method POST -Headers @{
        "X-KJDS-API-Key" = $ApiKey
    }
    if (-not $call.ok) {
        return [ordered]@{
            ok = $false
            skipped = $false
            error = $call.error
            project_id = "kjds-059-bas123"
            database_revision = $null
            observation_bucket = $null
            operating_subject_actor_id = $null
            subject_binding_sha256 = $null
            result_sha256 = $null
            states = $null
            counts = $null
        }
    }
    $data = $call.data
    $stateValues = @(
        $data.states.operating_subject,
        $data.states.scope_authority,
        $data.states.m0,
        $data.states.m1,
        $data.states.m2,
        $data.states.m3,
        $data.states.m4
    )
    $allowedStates = @("passed", "blocked", "no_data")
    $revisionMatch = [regex]::Match(
        [string]$data.database_revision,
        "^\d{8}_(\d{4})$"
    )
    $revisionValid = (
        $revisionMatch.Success -and
        [int]$revisionMatch.Groups[1].Value -ge 70
    )
    $valid =
        $data.contract_id -eq "kjds-operating-gate-observer-v1" -and
        $data.project_id -eq "kjds-059-bas123" -and
        $revisionValid -and
        $data.observation_bucket -and
        $data.operating_subject_actor_id -and
        $data.operating_subject_actor_id -cne $MonitorActorId -and
        $data.subject_binding_sha256 -match "^[0-9a-f]{64}$" -and
        $data.result_sha256 -match "^[0-9a-f]{64}$" -and
        $data.external_write_allowed -eq $false -and
        $data.model_self_certification_allowed -eq $false -and
        $data.counts.tasks -ge 6 -and
        $data.counts.observations -ge 6 -and
        $data.counts.nodes -ge 6 -and
        $stateValues.Count -eq 7 -and
        -not ($stateValues | Where-Object { $_ -notin $allowedStates })
    return [ordered]@{
        ok = $valid
        skipped = $false
        error = $(if ($valid) { $null } else { "Agent Gate observation contract failed closed" })
        project_id = $data.project_id
        database_revision = $data.database_revision
        observation_bucket = $data.observation_bucket
        operating_subject_actor_id = $data.operating_subject_actor_id
        subject_binding_sha256 = $data.subject_binding_sha256
        result_sha256 = $data.result_sha256
        states = $data.states
        counts = $data.counts
    }
}

$snapshotScript = "D:\AI\Apps\OpenClaw\workspace-chief\scripts\save-openclaw-health-snapshot.ps1"
$radarHealth = "D:\KJDS\kjds\.runtime\authority-radar\authority-radar-health.json"
$collectorTask = "KJDS-Authority-Radar"
$snapshotResult = if ($ControlPlaneOnly) {
    [ordered]@{ ok = $true; error = $null }
} else {
    Invoke-BoundedSnapshot -ScriptPath $snapshotScript
}
$snapshotOk = $snapshotResult.ok
$snapshotError = $snapshotResult.error

$radarAgeMinutes = $null
if (-not $ControlPlaneOnly -and (Test-Path -LiteralPath $radarHealth)) {
    $radarAgeMinutes = [math]::Round(((Get-Date) - (Get-Item -LiteralPath $radarHealth).LastWriteTime).TotalMinutes, 1)
}

$collectorTriggered = $false
if (-not $ControlPlaneOnly -and ($null -eq $radarAgeMinutes -or $radarAgeMinutes -gt 75)) {
    try {
        Start-ScheduledTask -TaskName $collectorTask
        $collectorTriggered = $true
    }
    catch {
        $snapshotError = (($snapshotError, $_.Exception.Message) | Where-Object { $_ }) -join "; "
    }
}

$controlPlaneUrl = (Get-Setting "KJDS_CONTROL_PLANE_URL" "http://127.0.0.1:8000").TrimEnd("/")
$controlPlaneApiKey = Get-Setting "KJDS_API_KEY"
$monitorApiKey = Get-Setting "KJDS_MONITOR_API_KEY"
$integrityPageSizeSetting = Get-BoundedIntegerSetting `
    -Name "KJDS_EVIDENCE_SCAN_PAGE_SIZE" -Default 500 -Minimum 1 -Maximum 1000
$integrityMaxPagesSetting = Get-BoundedIntegerSetting `
    -Name "KJDS_EVIDENCE_SCAN_MAX_PAGES" -Default 20 -Minimum 1 -Maximum 1000
$monitorIdentity = Test-MonitorIdentityConfiguration `
    -ApiKey $monitorApiKey `
    -CredentialJson (Get-Setting "KJDS_API_KEYS_JSON") `
    -DisallowedKeys @(
        $controlPlaneApiKey,
        (Get-Setting "KJDS_EXECUTOR_API_KEY"),
        (Get-Setting "KJDS_PILOT_READER_API_KEY"),
        (Get-Setting "OZON_API_KEY")
    )
$controlPlane = Test-HttpEndpoint -Uri "$controlPlaneUrl/health/ready"
$readiness = [ordered]@{
    ok = $false
    status = $null
    error = "skipped: KJDS_API_KEY is not configured"
}
if ($controlPlaneApiKey) {
    $readiness = Test-HttpEndpoint -Uri "$controlPlaneUrl/v1/operations/readiness" -Headers @{
        "X-KJDS-API-Key" = $controlPlaneApiKey
    }
}
$integrity = if (-not $monitorIdentity.ok) {
    [ordered]@{
        ok = $false
        skipped = $true
        error = $monitorIdentity.error
        pages = 0
        scanned = 0
        invalid = 0
        incident_count = 0
        last_scan_evidence_id = $null
        completed = $false
    }
} elseif (-not $integrityPageSizeSetting.ok -or -not $integrityMaxPagesSetting.ok) {
    [ordered]@{
        ok = $false
        skipped = $true
        error = (($integrityPageSizeSetting.error, $integrityMaxPagesSetting.error) | Where-Object { $_ }) -join "; "
        pages = 0
        scanned = 0
        invalid = 0
        incident_count = 0
        last_scan_evidence_id = $null
        completed = $false
    }
} else {
    Invoke-EvidenceIntegritySweep `
        -BaseUrl $controlPlaneUrl `
        -ApiKey $monitorApiKey `
        -PageSize $integrityPageSizeSetting.value `
        -MaxPages $integrityMaxPagesSetting.value
}
$agentGateObservation = if (-not $monitorIdentity.ok) {
    [ordered]@{
        ok = $false
        skipped = $true
        error = $monitorIdentity.error
        project_id = "kjds-059-bas123"
        database_revision = $null
        observation_bucket = $null
        operating_subject_actor_id = $null
        subject_binding_sha256 = $null
        result_sha256 = $null
        states = $null
        counts = $null
    }
} else {
    Invoke-AgentGateObservation `
        -BaseUrl $controlPlaneUrl `
        -ApiKey $monitorApiKey `
        -MonitorActorId $monitorIdentity.actor
}

$skippedDependency = [ordered]@{ ok = $true; status = $null; error = $null; skipped = $true }

$result = [ordered]@{
    generated_at = (Get-Date).ToString("o")
    snapshot = [ordered]@{ ok = $snapshotOk; error = $snapshotError }
    gateway = if ($ControlPlaneOnly) { $skippedDependency } else { Test-HttpEndpoint -Uri "http://127.0.0.1:18789/" }
    n8n = if ($ControlPlaneOnly) { $skippedDependency } else { Test-HttpEndpoint -Uri "http://127.0.0.1:5678/healthz" }
    ollama = if ($ControlPlaneOnly) { $skippedDependency } else { Test-HttpEndpoint -Uri "http://127.0.0.1:11434/api/tags" }
    control_plane = $controlPlane
    operations_readiness = $readiness
    evidence_integrity = $integrity
    agent_gate_observation = $agentGateObservation
    authority_radar = [ordered]@{
        health_file = $radarHealth
        age_minutes = $radarAgeMinutes
        collector_triggered = $collectorTriggered
    }
}

$result | ConvertTo-Json -Depth 8

$requiredControlPlane = $ControlPlaneOnly -or (Get-Setting "KJDS_HEALTH_REQUIRED" "false").ToLowerInvariant() -eq "true"
$failed =
    -not $result.snapshot.ok -or
    (-not $ControlPlaneOnly -and (-not $result.gateway.ok -or -not $result.n8n.ok -or -not $result.ollama.ok)) -or
    ($requiredControlPlane -and (
        -not $result.control_plane.ok -or
        -not $result.operations_readiness.ok -or
        -not $result.evidence_integrity.ok -or
        -not $result.agent_gate_observation.ok
    ))
if ($failed) { exit 2 }
exit 0
