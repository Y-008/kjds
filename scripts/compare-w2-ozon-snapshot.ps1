param(
    [string]$EvidenceDir = 'docs\project\evidence',
    [string]$BaselineName = '20260815_W2_AI_SNAPSHOT_BASELINE.json',
    [string]$LatestName = '20260815_W2_AI_SNAPSHOT_LATEST.json'
)

$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$evidenceDir = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $EvidenceDir))
$baselinePath = Join-Path $evidenceDir $BaselineName
$latestPath = Join-Path $evidenceDir $LatestName

foreach ($file in @($baselinePath, $latestPath)) {
    if (-not (Test-Path -LiteralPath $file)) {
        throw "Snapshot file not found: $file"
    }
}

$baseline = Get-Content -LiteralPath $baselinePath -Raw | ConvertFrom-Json
$latest = Get-Content -LiteralPath $latestPath -Raw | ConvertFrom-Json

function Get-CompanyMetrics($company) {
    $active = 0
    $delivered = 0
    $cancelled = 0
    if ($null -ne $company.orders -and $null -ne $company.orders.result) {
        foreach ($order in $company.orders.result) {
            switch ($order.status_alias) {
                'awaiting_packaging' { $active += [int]$order.count }
                'awaiting_deliver'    { $active += [int]$order.count }
                'delivering'          { $active += [int]$order.count }
                'delivered'           { $delivered = [int]$order.count }
                'cancelled'           { $cancelled = [int]$order.count }
            }
        }
    }
    return [PSCustomObject]@{
        balance = if ($company.balance.balance.end_amount) { [double]$company.balance.balance.end_amount.amount } else { $null }
        accrued = if ($company.balance.balance.accrued) { [double]$company.balance.balance.accrued.amount } else { $null }
        paid = if ($company.balance.balance.paid) { [double]($company.balance.balance.paid | Select-Object -First 1).amount } else { $null }
        active_fbs = $active
        delivered = $delivered
        cancelled = $cancelled
        blocked_warehouses = if ($company.warehouse_summary.blocked) { [int]$company.warehouse_summary.blocked } else { $null }
        warehouse_total = if ($company.warehouse_summary.total) { [int]$company.warehouse_summary.total } else { $null }
        premium_available = $company.premium.premium_available
        in_sale = if ($company.product_summary.in_sale) { [int]$company.product_summary.in_sale } else { $null }
        to_supply = if ($company.product_summary.to_supply) { [int]$company.product_summary.to_supply } else { $null }
    }
}

$changes = @()
foreach ($company in $latest.companies) {
    $baseCompany = $baseline.companies | Where-Object { $_.id -eq $company.id } | Select-Object -First 1
    if ($null -eq $baseCompany) {
        $changes += [PSCustomObject]@{ Store = $company.name; Field = '(new company)'; Baseline = '-'; Latest = $company.id; Status = 'NEW' }
        continue
    }
    $a = Get-CompanyMetrics $baseCompany
    $b = Get-CompanyMetrics $company
    $pairs = [ordered]@{
        'balance' = @($a.balance, $b.balance)
        'accrued' = @($a.accrued, $b.accrued)
        'paid' = @($a.paid, $b.paid)
        'active_fbs' = @($a.active_fbs, $b.active_fbs)
        'delivered' = @($a.delivered, $b.delivered)
        'cancelled' = @($a.cancelled, $b.cancelled)
        'blocked_warehouses' = @($a.blocked_warehouses, $b.blocked_warehouses)
        'warehouse_total' = @($a.warehouse_total, $b.warehouse_total)
        'premium_available' = @($a.premium_available, $b.premium_available)
        'in_sale' = @($a.in_sale, $b.in_sale)
        'to_supply' = @($a.to_supply, $b.to_supply)
    }
    foreach ($field in $pairs.Keys) {
        $old = $pairs[$field][0]
        $new = $pairs[$field][1]
        if ("$old" -ne "$new") {
            $changes += [PSCustomObject]@{
                Store = $company.name
                Field = $field
                Baseline = $old
                Latest = $new
                Status = 'CHANGED'
            }
        }
    }
}

if ($changes.Count -eq 0) {
    Write-Output 'W2 snapshot comparison: NO_CHANGE'
}
else {
    $changes | Format-Table -AutoSize
}