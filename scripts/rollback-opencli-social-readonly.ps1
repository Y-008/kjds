[CmdletBinding()]
param(
    [ValidateSet("Verify", "Apply")]
    [string]$Mode = "Verify"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$paths = @(
    "docs/project/registries/social_intelligence_read_allowlist.json",
    "scripts/manage-opencli-social-readonly.ps1",
    "scripts/rollback-opencli-social-readonly.ps1",
    "tests/test_opencli_social_readonly_contract.py",
    "docs/project/evidence/20260804_OPENCLI_SOCIAL_READONLY_VERIFICATION.md",
    "docs/project/evidence/20260804_OPENCLI_SOCIAL_READONLY_INTAKE.patch"
)

Push-Location $repoRoot
try {
    $commits = @(
        foreach ($path in $paths) {
            (& git log --diff-filter=A --format=%H -1 -- $path).Trim()
        }
    ) | Where-Object { $_ } | Sort-Object -Unique
    if ($commits.Count -ne 1) {
        throw "Rollback paths do not share one introducing commit: $($commits -join ',')"
    }
    $introducingCommit = $commits[0]
    & git merge-base --is-ancestor $introducingCommit HEAD
    if ($LASTEXITCODE -ne 0) {
        throw "Introducing commit is not an ancestor of HEAD: $introducingCommit"
    }
    foreach ($path in $paths) {
        & git cat-file -e "$introducingCommit`:$path"
        if ($LASTEXITCODE -ne 0) {
            throw "Rollback path is absent from introducing commit: $path"
        }
    }
    $dirty = @(
        git status --short -- @paths
    ) | Where-Object { $_ }
    if ($dirty.Count -gt 0) {
        throw "Rollback target paths contain uncommitted changes."
    }
    $result = [ordered]@{
        status = "verified"
        introducing_commit = $introducingCommit
        target_count = $paths.Count
        command = "git revert --no-edit $introducingCommit"
    }
    if ($Mode -eq "Apply") {
        & git revert --no-edit $introducingCommit
        if ($LASTEXITCODE -ne 0) {
            throw "git revert failed for $introducingCommit"
        }
        $result.status = "applied"
        $result["rollback_commit"] = (& git rev-parse HEAD).Trim()
    }
    $result | ConvertTo-Json -Depth 4
} finally {
    Pop-Location
}
