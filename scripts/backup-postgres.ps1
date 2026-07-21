[CmdletBinding()]
param(
    [string]$OutputDirectory = "backups",
    [string]$Database = $(if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "hermes" })
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

if ($Database -notmatch '^[A-Za-z0-9_]+$') {
    throw "Database must contain only letters, numbers, and underscores."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$outputPath = if ([System.IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory
} else {
    Join-Path $repoRoot $OutputDirectory
}
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null

Push-Location $repoRoot
try {
    docker compose up -d postgres | Out-Null
    $containerId = (docker compose ps -q postgres).Trim()
    if (-not $containerId) {
        throw "PostgreSQL container is not running."
    }

    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $baseName = "kjds-$Database-$stamp"
    $archivePath = Join-Path $outputPath "$baseName.dump"
    $manifestPath = "$archivePath.manifest.json"
    $containerArchive = "/tmp/$baseName.dump"
    $postgresUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "hermes" }

    try {
        docker compose exec -T postgres pg_dump -U $postgresUser --format=custom --no-owner --no-acl --dbname=$Database --file=$containerArchive
        if ($LASTEXITCODE -ne 0) { throw "pg_dump failed." }
        docker cp "${containerId}:$containerArchive" $archivePath | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Could not copy backup from PostgreSQL container." }
    } finally {
        docker compose exec -T postgres rm -f $containerArchive 2>$null | Out-Null
    }

    $hash = Get-Sha256 $archivePath
    $bytes = (Get-Item -LiteralPath $archivePath).Length
    $head = (docker compose exec -T postgres psql -U $postgresUser -d $Database -Atc "SELECT version_num FROM alembic_version LIMIT 1;").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $head) { throw "Could not read Alembic head from backup source." }

    [ordered]@{
        manifest_version = 1
        created_at = (Get-Date).ToUniversalTime().ToString("o")
        database = $Database
        archive = (Split-Path -Leaf $archivePath)
        sha256 = $hash
        bytes = $bytes
        alembic_head = $head
        format = "pg_dump-custom"
    } | ConvertTo-Json | Set-Content -LiteralPath $manifestPath -Encoding utf8

    Write-Output ([ordered]@{
        archive = (Resolve-Path -LiteralPath $archivePath).Path
        manifest = (Resolve-Path -LiteralPath $manifestPath).Path
        sha256 = $hash
        alembic_head = $head
    } | ConvertTo-Json)
} finally {
    Pop-Location
}
