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
