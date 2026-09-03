param(
    [string]$EvidenceDir = 'docs\project\evidence'
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$evidenceDir = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $EvidenceDir))
if (-not (Test-Path -LiteralPath $evidenceDir)) {
    throw "Evidence directory not found: $evidenceDir"
}

$nodeScript = Join-Path $PSScriptRoot 'capture_w2_ozon_cdp_snapshot.mjs'
if (-not (Test-Path -LiteralPath $nodeScript)) {
    throw "Snapshot script not found: $nodeScript"
}

$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$timestampPath = Join-Path $evidenceDir "20260815_W2_AI_SNAPSHOT_$stamp.json"
$latestPath = Join-Path $evidenceDir '20260815_W2_AI_SNAPSHOT_LATEST.json'

$cdpBase = if ($env:CDP_BASE) { $env:CDP_BASE.TrimEnd('/') } else { 'http://127.0.0.1:9224' }
try {
    $null = Invoke-RestMethod -Uri "$cdpBase/json/version" -TimeoutSec 5
}
catch {
    Write-Warning 'CDP 9224 unavailable; snapshot not generated.'
    exit 2
}
try {
    $pages = @(Invoke-RestMethod -Uri "$cdpBase/json/list" -TimeoutSec 5)
}
catch {
    Write-Warning 'CDP page list unavailable; snapshot not generated.'
    exit 2
}
$sellerPage = $pages | Where-Object { $_.type -eq 'page' -and $_.url -match 'seller\.ozon\.ru' } | Select-Object -First 1
if ($null -eq $sellerPage) {
    Write-Warning 'No Ozon seller page found; snapshot not generated.'
    exit 2
}
if ($sellerPage.url -match '/app/registration/signin') {
    Write-Warning 'Ozon page is signin, not an authenticated seller workspace; snapshot not generated.'
    exit 2
}
$env:W2_SNAPSHOT_OUT = $timestampPath
try {
    & node $nodeScript
    if ($LASTEXITCODE -ne 0) {
        throw "Node snapshot script failed with exit code $LASTEXITCODE"
    }
}
finally {
    Remove-Item Env:\W2_SNAPSHOT_OUT -ErrorAction SilentlyContinue
}

Copy-Item -LiteralPath $timestampPath -Destination $latestPath -Force

$files = @($timestampPath, $latestPath)
$results = foreach ($file in $files) {
    $item = Get-Item -LiteralPath $file
        $sha = [System.Security.Cryptography.SHA256]::Create()
        $hashBytes = $sha.ComputeHash([System.IO.File]::ReadAllBytes($file))
        $sha.Dispose()
        $hashString = [System.BitConverter]::ToString($hashBytes).Replace('-', '')
    [PSCustomObject]@{
        Path = $item.FullName
        Bytes = $item.Length
        SHA256 = $hashString
    }
}
$results | Format-List

Write-Host ''
try {
    $latest = Get-Content -LiteralPath $latestPath -Raw | ConvertFrom-Json
    $summary = foreach ($company in $latest.companies) {
        $active = 0
        foreach ($order in $company.orders.result) {
            if ($order.status_alias -in @('awaiting_packaging', 'awaiting_deliver', 'delivering')) {
                $active += [int]$order.count
            }
        }
        [PSCustomObject]@{
            Store             = $company.name
            Balance           = $company.balance.balance.end_amount.amount
            ActiveFBS         = $active
            BlockedWarehouses = $company.warehouse_summary.blocked
            WarehouseTotal    = $company.warehouse_summary.total
            PremiumAvailable  = $company.premium.premium_available
            InSale           = $company.product_summary.in_sale
            ToSupply         = $company.product_summary.to_supply
        }
    }
    $summary | Format-Table -AutoSize
}
catch {
    Write-Warning "Could not summarize snapshot: $($_.Exception.Message)"
}

$compareScript = Join-Path $PSScriptRoot 'compare-w2-ozon-snapshot.ps1'
if (Test-Path -LiteralPath $compareScript) {
    Write-Host ''
    & $compareScript
}

Write-Host 'Snapshot complete. No Ozon store write operations were performed.'
