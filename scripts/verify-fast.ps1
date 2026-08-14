param(
    [switch]$Sync,
    [string[]]$Tests = @(
        "tests/test_ai_listing_fenced_lease.py",
        "tests/test_g1_harness_contract.py",
        "tests/test_automated_commerce.py",
        "tests/test_commercial_lifecycle.py"
    )
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Get-RunningVerificationProcesses {
    if ($IsWindows) {
        return Get-CimInstance Win32_Process | Where-Object {
            $_.ProcessId -ne $PID -and ($_.CommandLine -like '*verify-g1.ps1*' -or $_.CommandLine -like '*python -m pytest*')
        }
    }
    $rows = & ps -eo pid=,args=
    foreach ($row in $rows) {
        if ($row -match '^\s*(\d+)\s+(.*)$') {
            $pidValue = [int]$Matches[1]
            $cmdline = $Matches[2]
            if ($pidValue -ne $PID -and ($cmdline -match 'verify-g1\.ps1|python -m pytest')) {
                [pscustomobject]@{ ProcessId = $pidValue; CommandLine = $cmdline }
            }
        }
    }
}

$busy = @(Get-RunningVerificationProcesses)
if ($busy) {
    Write-Warning "Another verification process is already running:"
    $busy | Select-Object ProcessId, CommandLine | Format-List
    Write-Output "verify-fast BLOCKED"
    exit 1
}

if ($Sync) {
    Write-Host "== uv sync =="
    uv sync --extra dev --locked
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }
}

Write-Host "== ruff =="
uv run ruff check .
if ($LASTEXITCODE -ne 0) { throw "ruff check failed" }

Write-Host "== pytest focused =="
$PytestTemp = Join-Path (Join-Path $Root ".runtime") "pytest-local"
$pytestArgs = @("-q", "-p", "no:cacheprovider", "--basetemp", $PytestTemp)
$pytestArgs += $Tests
& uv run pytest @pytestArgs
if ($LASTEXITCODE -ne 0) { throw "pytest failed" }

Write-Host "== git diff --check =="
git diff --check
if ($LASTEXITCODE -ne 0) { throw "git diff --check failed" }

Write-Host "verify-fast PASS"
