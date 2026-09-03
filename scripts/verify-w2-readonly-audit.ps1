param(
    [string]$EvidenceDir = 'docs\project\evidence'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$evidenceDir = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $EvidenceDir))
$manifestPath = Join-Path $evidenceDir '20260815_W2_GENERATED_ARTIFACTS_MANIFEST.md'
$baselinePath = Join-Path $evidenceDir '20260815_W2_AI_SNAPSHOT_BASELINE.json'
$latestPath = Join-Path $evidenceDir '20260815_W2_AI_SNAPSHOT_LATEST.json'
$compareScript = Join-Path $PSScriptRoot 'compare-w2-ozon-snapshot.ps1'

$issues = [System.Collections.Generic.List[string]]::new()
function Add-Issue([string]$message) { $script:issues.Add($message) }

if (-not (Test-Path -LiteralPath $manifestPath)) { Add-Issue "Missing manifest: $manifestPath" }
if (-not (Test-Path -LiteralPath $baselinePath)) { Add-Issue "Missing baseline: $baselinePath" }
if (-not (Test-Path -LiteralPath $latestPath)) { Add-Issue "Missing latest: $latestPath" }

$docFiles = @(Get-ChildItem -LiteralPath $evidenceDir -Filter '20260815_W2_*' | Where-Object { $_.Name -ne '20260815_W2_GENERATED_ARTIFACTS_MANIFEST.md' } | Sort-Object Name)
$scriptFiles = @(
    (Get-Item -LiteralPath (Join-Path $repoRoot 'scripts\capture_w2_ozon_cdp_snapshot.mjs')),
    (Get-Item -LiteralPath (Join-Path $repoRoot 'scripts\run-w2-readonly-snapshot.ps1')),
    (Get-Item -LiteralPath (Join-Path $repoRoot 'scripts\compare-w2-ozon-snapshot.ps1')),
    (Get-Item -LiteralPath (Join-Path $repoRoot 'scripts\verify-w2-readonly-audit.ps1'))
)

function Get-Sha256([string]$filePath) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return [System.BitConverter]::ToString($sha.ComputeHash([System.IO.File]::ReadAllBytes($filePath))).Replace('-', '') }
    finally { $sha.Dispose() }
}

# Manifest hash and size verification.
$manifestChecked = 0
if (Test-Path -LiteralPath $manifestPath) {
    foreach ($line in Get-Content -LiteralPath $manifestPath) {
        if ($line -match '^\|\s*(docs/project/[^|]+?|scripts/[^|]+?)\s*\|\s*([0-9A-F]{64})\s*\|\s*(\d+)\s*\|$') {
            $rel = $Matches[1].Trim()
            $expectedHash = $Matches[2]
            $expectedBytes = [int]$Matches[3]
            $fullPath = Join-Path $repoRoot ($rel -replace '/', '\')
            if (-not (Test-Path -LiteralPath $fullPath)) {
                Add-Issue "Manifest missing file: $rel"
                continue
            }
            $actualHash = Get-Sha256 $fullPath
            $actualItem = Get-Item -LiteralPath $fullPath
            $manifestChecked++
            if ($actualHash -ne $expectedHash -or $actualItem.Length -ne $expectedBytes) {
                Add-Issue "Manifest mismatch: $rel expected=$expectedHash/$expectedBytes actual=$actualHash/$($actualItem.Length)"
            }
        }
    }
}

# JSON parse.
foreach ($jsonPath in @($baselinePath, $latestPath)) {
    if (Test-Path -LiteralPath $jsonPath) {
        try { $null = Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json }
        catch { Add-Issue "JSON parse failed: $jsonPath :: $($_.Exception.Message)" }
    }
}

# Reference integrity.
$refCount = 0
foreach ($file in $docFiles) {
    $text = [System.IO.File]::ReadAllText($file.FullName)
    $matches = [regex]::Matches($text, '(?<![A-Za-z0-9_/])(?:docs[\\/]project[\\/]evidence[\\/]20260815_W2_[A-Z0-9_]+\.(?:md|json)|scripts[\\/](?:capture_w2_ozon_cdp_snapshot\.mjs|run-w2-readonly-snapshot\.ps1|compare-w2-ozon-snapshot\.ps1)|docs[\\/]project[\\/]24[A-Za-z0-9_]+\.md)')
    foreach ($match in $matches) {
        $rel = $match.Value -replace '\\', '/'
        $refCount++
        if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $rel))) { Add-Issue "Broken reference from $($file.Name): $rel" }
    }
}

# Secret literal scan on Markdown W2 files.
foreach ($file in $docFiles | Where-Object { $_.Extension -eq '.md' }) {
    $text = [System.IO.File]::ReadAllText($file.FullName)
    if ($text -match '(?i)(Api-Key\s*[=:]\s*["''][A-Za-z0-9_-]{8,}|Client-Id\s*[=:]\s*["''][0-9]{3,}|BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY)') {
        Add-Issue "Secret literal detected: $($file.Name)"
    }
}

# Script syntax.
$nodeCheck = & node --check (Join-Path $repoRoot 'scripts\capture_w2_ozon_cdp_snapshot.mjs') 2>&1
if ($LASTEXITCODE -ne 0) { Add-Issue "Node syntax failed: $nodeCheck" }
foreach ($script in $scriptFiles | Where-Object { $_.Extension -eq '.ps1' }) {
    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($script.FullName, [ref]$tokens, [ref]$parseErrors) | Out-Null
    if ($parseErrors.Count -ne 0) { Add-Issue "PowerShell parse failed: $($script.Name)" }
}

# Git state for W2 deliverables.
$trackPaths = @($docFiles.FullName) + @($scriptFiles.FullName)
$relativePaths = $trackPaths | ForEach-Object { $_.Substring($repoRoot.Length).TrimStart('\').Replace('\', '/') }
$tracked = @(git ls-files -- $relativePaths)
$staged = @(git diff --cached --name-only -- $relativePaths)
$untracked = @(git ls-files --others --exclude-standard -- $relativePaths)
if ($tracked.Count -ne 0) { Add-Issue "W2 deliverables are tracked: $($tracked.Count)" }
if ($staged.Count -ne 0) { Add-Issue "W2 deliverables are staged: $($staged.Count)" }
if ((Test-Path -LiteralPath (Join-Path $repoRoot '.git\index.lock'))) { Add-Issue 'Git index.lock exists' }

[pscustomobject]@{
    W2_DOCS = $docFiles.Count
    W2_SCRIPTS = $scriptFiles.Count
    MANIFEST_CHECKED = $manifestChecked
    REF_COUNT = $refCount
    TRACKED = $tracked.Count
    STAGED = $staged.Count
    UNTRACKED = $untracked.Count
    INDEX_LOCK = (Test-Path -LiteralPath (Join-Path $repoRoot '.git\index.lock'))
    ISSUES = $issues.Count
} | Format-List

if ($issues.Count -ne 0) {
    Write-Output 'W2 audit issues:'
    $issues | ForEach-Object { Write-Output "- $_" }
    exit 1
}

Write-Output 'W2 readonly audit: PASS'
exit 0