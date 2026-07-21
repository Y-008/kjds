[CmdletBinding()]
param(
    [string]$Destination
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$source = Join-Path $repoRoot "web\public\startup"

if ([string]::IsNullOrWhiteSpace($Destination)) {
    $Destination = Join-Path $repoRoot ".runtime\startup-intake"
}

$templates = @(Get-ChildItem -LiteralPath $source -Filter "*.csv" -File)
if ($templates.Count -ne 8) {
    throw "Expected exactly eight startup CSV templates, found $($templates.Count)."
}

$directory = New-Item -ItemType Directory -Path $Destination -Force
$added = @()
$preserved = @()
foreach ($template in $templates) {
    $target = Join-Path $directory.FullName $template.Name
    if (Test-Path -LiteralPath $target) {
        if (-not (Test-Path -LiteralPath $target -PathType Leaf)) {
            throw "Startup template target exists but is not a file: $target"
        }
        $preserved += $template.Name
        continue
    }
    Copy-Item -LiteralPath $template.FullName -Destination $target
    $added += $template.Name
}

[ordered]@{
    status = if ($preserved.Count) { "updated" } else { "prepared" }
    directory = $directory.FullName
    template_count = $templates.Count
    added_templates = $added
    preserved_templates = $preserved
    git_ignored_default = $directory.FullName.StartsWith((Join-Path $repoRoot ".runtime"))
    formal_fact_promoted = $false
    warning = "Do not store passwords, API keys, tokens, full bank account numbers, or identity documents in these CSV files. Media rows must reference real files and rights evidence; the CSV is not the evidence itself."
} | ConvertTo-Json
