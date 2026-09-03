<#
.SYNOPSIS
  Produce a redacted, read-only report for the real Ozon operating gates.

.DESCRIPTION
  This script never prints or transmits credentials, cookies, CAPTCHA data,
  bank details, or model keys. It only reports presence bits, local TCP state,
  and the HTTP status/anti-bot signal from the official Ozon origin. A 2xx
  response is not treated as proof of seller authorization; current seller
  facts still require the governed Ozon Worker and official readback Evidence.
#>

$ErrorActionPreference = "Stop"
$workspaceRoot = (Get-Location).Path
$dotenvPath = Join-Path $workspaceRoot ".env"
$dotenvValues = @{}

if (Test-Path -LiteralPath $dotenvPath) {
    foreach ($line in Get-Content -LiteralPath $dotenvPath) {
        if ($line -match '^\s*([^#=\s]+)\s*=\s*(.*)$') {
            $dotenvValues[$matches[1]] = $matches[2].Trim()
        }
    }
}

function Test-GateValue {
    param([Parameter(Mandatory)][string]$Name)

    $processValue = [Environment]::GetEnvironmentVariable($Name)
    $dotenvValue = if ($dotenvValues.ContainsKey($Name)) { $dotenvValues[$Name] } else { "" }
    return [ordered]@{
        process_present = -not [string]::IsNullOrWhiteSpace($processValue)
        dotenv_present = -not [string]::IsNullOrWhiteSpace($dotenvValue)
    }
}

$credentialNames = @(
    "OZON_CLIENT_ID",
    "OZON_API_KEY",
    "OZON_WRITE_CLIENT_ID",
    "OZON_WRITE_API_KEY"
)
$runtimeNames = @(
    "KJDS_DATABASE_URL",
    "KJDS_CHANNEL_LEASE_SIGNING_KEY",
    "KJDS_CHANNEL_LEASE_ISSUER",
    "KJDS_CHANNEL_LEASE_KEY_ID",
    "KJDS_OZON_EXECUTION_IDENTITY_REF",
    "KJDS_PILOT_READER_API_KEY",
    "KJDS_OLLAMA_URL",
    "KJDS_OPENAI_COMPAT_BASE_URL",
    "KJDS_OPENAI_COMPAT_API_KEY",
    "KJDS_OPENAI_COMPAT_TEXT_MODEL",
    "KJDS_OPENAI_COMPAT_VISION_MODEL"
)

$port9225 = Test-NetConnection -ComputerName 127.0.0.1 -Port 9225 -InformationLevel Quiet -WarningAction SilentlyContinue
$ozonStatus = $null
$ozonAntiBot = $false
try {
    $response = Invoke-WebRequest -Uri "https://api-seller.ozon.ru" -Method Head -TimeoutSec 20 -UseBasicParsing
    $ozonStatus = [int]$response.StatusCode
    $ozonAntiBot = $null -ne $response.Headers["ozon-antibot"]
} catch {
    $errorResponse = $_.Exception.Response
    if ($null -ne $errorResponse -and $null -ne $errorResponse.StatusCode) {
        $ozonStatus = [int]$errorResponse.StatusCode
        $ozonAntiBot = $null -ne $errorResponse.Headers["ozon-antibot"]
    }
}

$credentialReport = [ordered]@{}
foreach ($name in $credentialNames) {
    $credentialReport[$name] = Test-GateValue -Name $name
}
$runtimeReport = [ordered]@{}
foreach ($name in $runtimeNames) {
    $runtimeReport[$name] = Test-GateValue -Name $name
}

$missingRuntime = @(
    $runtimeNames | Where-Object {
        $report = $runtimeReport[$_]
        -not ($report.process_present -or $report.dotenv_present)
    }
)
$blockers = [System.Collections.Generic.List[string]]::new()
if (-not $port9225) { $blockers.Add("BROWSER_9225_OFFLINE") }
if ($missingRuntime.Count -gt 0) { $blockers.Add("RUNTIME_SECRET_OR_IDENTITY_MISSING") }
if ($ozonAntiBot) { $blockers.Add("OZON_OFFICIAL_ORIGIN_ANTIBOT") }
$blockers.Add("REALFBS_OFFICIAL_CONFIRMATION_REQUIRED")
$blockers.Add("BANK_ORIGINAL_EVIDENCE_REQUIRED")

[ordered]@{
    contract_id = "kjds-real-ozon-gate-check-v1"
    checked_at_utc = [DateTime]::UtcNow.ToString("o")
    workspace = $workspaceRoot
    official_origin = "https://api-seller.ozon.ru"
    official_origin_http_status = $ozonStatus
    official_origin_reachable = $null -ne $ozonStatus
    official_origin_antibot = $ozonAntiBot
    browser_9225_tcp = [bool]$port9225
    credential_presence_only = $credentialReport
    runtime_presence_only = $runtimeReport
    unresolved_runtime_names = $missingRuntime
    realfbs_official_confirmation = "not_verified"
    bank_cash_state = "CASH_UNKNOWN"
    external_writes_performed = $false
    blockers = @($blockers)
    status = if ($blockers.Count -eq 0) { "READY_FOR_SEPARATE_OFFICIAL_READBACK" } else { "BLOCKED" }
} | ConvertTo-Json -Depth 8
