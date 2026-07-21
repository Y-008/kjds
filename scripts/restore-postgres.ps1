[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath,

    [Parameter(Mandatory = $true)]
    [string]$TargetDatabase,

    [switch]$AllowDefaultDatabase
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-Sha256([string]$Path) {
    $command = Get-Command Get-FileHash -ErrorAction SilentlyContinue
    if ($command) {
        return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $stream = [System.IO.File]::OpenRead($Path)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($sha.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

if ($TargetDatabase -notmatch '^[A-Za-z0-9_]+$') {
    throw "TargetDatabase must contain only letters, numbers, and underscores."
}
$defaultDatabase = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "hermes" }
if ($TargetDatabase -eq $defaultDatabase -and -not $AllowDefaultDatabase) {
    throw "Refusing to replace the default database. Use a disposable target or pass -AllowDefaultDatabase explicitly."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$archivePath = (Resolve-Path -LiteralPath $BackupPath).Path
$manifestPath = "$archivePath.manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw "Backup manifest is missing: $manifestPath"
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$actualHash = Get-Sha256 $archivePath
if ($actualHash -ne $manifest.sha256) {
    throw "Backup hash does not match its manifest."
}
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

Push-Location $repoRoot
try {
    docker compose up -d postgres | Out-Null
    $containerId = (docker compose ps -q postgres).Trim()
    if (-not $containerId) { throw "PostgreSQL container is not running." }
    $postgresUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "hermes" }
    $containerArchive = "/tmp/kjds-restore-$([guid]::NewGuid().ToString('N')).dump"

    try {
        docker cp $archivePath "${containerId}:$containerArchive" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not copy backup into PostgreSQL container." }
        docker compose exec -T postgres psql -U $postgresUser -d postgres -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$TargetDatabase' AND pid <> pg_backend_pid();" | Out-Null
        docker compose exec -T postgres dropdb -U $postgresUser --if-exists $TargetDatabase
        docker compose exec -T postgres createdb -U $postgresUser $TargetDatabase
        docker compose exec -T postgres pg_restore -U $postgresUser --dbname=$TargetDatabase --no-owner --no-acl --exit-on-error $containerArchive
        if ($LASTEXITCODE -ne 0) { throw "pg_restore failed." }
    } finally {
        docker compose exec -T postgres rm -f $containerArchive 2>$null | Out-Null
    }

    $restoredHead = (docker compose exec -T postgres psql -U $postgresUser -d $TargetDatabase -Atc "SELECT version_num FROM alembic_version LIMIT 1;").Trim()
    if ($LASTEXITCODE -ne 0 -or $restoredHead -ne $manifest.alembic_head) {
        throw "Restored Alembic head '$restoredHead' does not match manifest '$($manifest.alembic_head)'."
    }

    $report = [ordered]@{
        status = "PASS"
        restored_at = (Get-Date).ToUniversalTime().ToString("o")
        elapsed_seconds = [math]::Round($stopwatch.Elapsed.TotalSeconds, 3)
        target_database = $TargetDatabase
        source_archive = $archivePath
        sha256 = $actualHash
        alembic_head = $restoredHead
    }
    $runtime = Join-Path $repoRoot ".runtime"
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    $reportPath = Join-Path $runtime "RESTORE_VERIFICATION.json"
    $report | ConvertTo-Json | Set-Content -LiteralPath $reportPath -Encoding utf8
    Write-Output ($report | ConvertTo-Json)
} finally {
    Pop-Location
}
