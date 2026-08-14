param(
    [switch]$IncludeCommands
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Format-MB([long]$Bytes) {
    if ($Bytes -ge 1MB) {
        return "{0:N1} MB" -f ($Bytes / 1MB)
    }
    if ($Bytes -ge 1KB) {
        return "{0:N1} KB" -f ($Bytes / 1KB)
    }
    return "$Bytes B"
}

Write-Host "=== git worktrees ==="
$worktrees = @()
$current = @{}
$worktreeLines = git worktree list --porcelain
foreach ($line in $worktreeLines) {
    if ($line -match '^worktree (.*)$') {
        if ($current.Path) { $worktrees += [pscustomobject]$current }
        $current = @{ Path = $Matches[1]; Detached = $false; Branch = ""; Head = "" }
    }
    elseif ($line -match '^HEAD (.*)$') {
        $current.Head = $Matches[1]
    }
    elseif ($line -match '^branch refs/heads/(.*)$') {
        $current.Branch = $Matches[1]
    }
    elseif ($line -match '^detached$') {
        $current.Detached = $true
    }
}
if ($current.Path) { $worktrees += [pscustomobject]$current }

$worktreeRows = foreach ($wt in $worktrees) {
    $dirty = $false
    $dirtyOut = git -c color.ui=false -C $wt.Path status --porcelain 2>$null
    if ($dirtyOut) { $dirty = $true }
    $state = if ($wt.Detached) { "detached" } else { $wt.Branch }
    [pscustomobject]@{
        Path  = $wt.Path
        State = $state
        Dirty = $dirty
    }
}
$worktreeRows | Sort-Object Path | Format-Table -AutoSize

Write-Host "=== upstream gone branches ==="
$goneRows = @()
$branchLines = git -c color.ui=false branch -vv
foreach ($line in $branchLines) {
    if ($line -notmatch '\[[^\]]*gone\]') { continue }
    $trimmed = $line.Trim()
    $checkedOut = $trimmed.StartsWith("+")
    $namePart = $trimmed.TrimStart("+").Trim()
    if ($namePart -notmatch '^(\S+)') { continue }
    $name = $Matches[1]
    $unique = git rev-list --count "main..$name" 2>$null
    if ($LASTEXITCODE -ne 0) { $unique = "?" }
    $subject = (git log -1 --oneline $name 2>$null | Select-Object -First 1)
    $goneRows += [pscustomobject]@{
        Branch                = $name
        CheckedOutInWorktree  = $checkedOut
        UniqueCommitsVsMain   = $unique
        LastSubject           = $subject
    }
}
$goneRows | Sort-Object Branch | Format-Table -AutoSize

Write-Host "=== disk usage ==="
$dirs = @(".runtime", ".verifier", ".tmp", ".pytest_cache", ".ruff_cache")
$dirRows = foreach ($d in $dirs) {
    $full = Join-Path $Root $d
    if (Test-Path -LiteralPath $full) {
        $files = Get-ChildItem -LiteralPath $full -Recurse -Force -File -ErrorAction SilentlyContinue
        $size = ($files | Measure-Object -Property Length -Sum).Sum
        $count = (Get-ChildItem -LiteralPath $full -Recurse -Force -ErrorAction SilentlyContinue | Measure-Object).Count
        [pscustomobject]@{
            Path  = $full
            Size  = Format-MB $size
            Items = $count
        }
    }
}
$dirRows | Sort-Object Path | Format-Table -AutoSize

Write-Host "=== pytest temporary directories ==="
$pytestDirs = @()
$pytestDirs += Get-ChildItem -LiteralPath (Join-Path $Root ".runtime") -Directory -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "pytest-*" } |
    Select-Object -ExpandProperty FullName
$pytestDirs += Get-ChildItem -LiteralPath $Root -Directory -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like ".pytest-*" } |
    Select-Object -ExpandProperty FullName
$pytestDirs | Sort-Object -Unique | ForEach-Object { Write-Output $_ }

if ($IncludeCommands) {
    Write-Host ""
    Write-Host "=== suggested cleanup commands (review before executing) ==="
    foreach ($wt in ($worktreeRows | Where-Object { $_.State -eq "detached" -and -not $_.Dirty } | Sort-Object Path)) {
        Write-Output ('git worktree remove "{0}"' -f $wt.Path)
    }
    foreach ($row in ($goneRows | Where-Object { -not $_.CheckedOutInWorktree } | Sort-Object Branch)) {
        Write-Output ('git branch -D "{0}" # review main..{0} first' -f $row.Branch)
    }
    foreach ($p in ($pytestDirs | Sort-Object -Unique)) {
        Write-Output ('Remove-Item -LiteralPath "{0}" -Recurse -Force' -f $p)
    }
}

Write-Host ""
Write-Host "audit-cleanup PASS"