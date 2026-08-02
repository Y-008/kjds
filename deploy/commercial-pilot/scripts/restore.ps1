[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectName,

    [Parameter(Mandatory = $true)]
    [string]$BackupPath,

    [Parameter(Mandatory = $true)]
    [string]$TargetDatabase,

    [string]$ComposeFile,

    [string]$EnvFile,

    [string]$CustomerScopeJson,

    [string]$CustomerScopeFile,

    [switch]$AllowDefaultDatabase
)

. (Join-Path $PSScriptRoot "_common.ps1")

if (-not $ComposeFile) {
    $ComposeFile = Join-Path (Get-CommercialPilotPackageRoot) "compose.production.yaml"
}
if (-not (Test-Path -LiteralPath $ComposeFile)) {
    throw "Compose file not found: $ComposeFile"
}
if ($ProjectName -notmatch '^[A-Za-z0-9_.-]+$') {
    throw "ProjectName must contain only letters, numbers, dot, underscore, or dash."
}
if ($TargetDatabase -notmatch '^[A-Za-z0-9_]+$') {
    throw "TargetDatabase must contain only letters, numbers, and underscores."
}

$archivePath = (Resolve-Path -LiteralPath $BackupPath).Path
$manifestPath = "$archivePath.manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw "Backup manifest is missing: $manifestPath"
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.manifest_version -ne 1 -or $manifest.format -ne "pg_dump-custom") {
    throw "Backup manifest version or format is unsupported."
}
$actualHash = Get-Sha256 -Path $archivePath
if ($actualHash -ne $manifest.sha256) {
    throw "Backup hash does not match its manifest."
}

$restoredEnv = [ordered]@{}
$locationPushed = $false
try {
    $composeArgs = @()
    if ($EnvFile) {
        $envFileValues = Import-DotEnvFile -Path $EnvFile
        foreach ($entry in $envFileValues.GetEnumerator()) {
            Set-ScopedEnvironmentValue -Snapshot $restoredEnv -Name $entry.Key -Value $entry.Value
        }
        $composeArgs += @("--env-file", $EnvFile)
    }
    $composeArgs += @("-f", $ComposeFile, "-p", $ProjectName)

    $scopeText = if ($CustomerScopeJson) {
        $CustomerScopeJson
    } elseif ($CustomerScopeFile) {
        Get-TextFromFile -Path $CustomerScopeFile
    } else {
        Get-TextFromEnvOrFile -ValueName "KJDS_CUSTOMER_SCOPE_JSON"
    }
    if (-not $scopeText) {
        throw "Customer scope JSON is required through -CustomerScopeJson, -CustomerScopeFile, or KJDS_CUSTOMER_SCOPE_JSON."
    }
    $scopeInfo = Get-CustomerScopeInfo -JsonText $scopeText
    if ($manifest.customer_scope_sha256 -ne $scopeInfo.sha256) {
        throw "Current customer scope does not match the backup manifest."
    }

    $defaultDatabase = [Environment]::GetEnvironmentVariable("KJDS_DATABASE_NAME")
    if (-not $defaultDatabase) {
        $defaultDatabase = "kjds"
    }
    if ($TargetDatabase -eq $defaultDatabase -and -not $AllowDefaultDatabase) {
        throw "Refusing to replace the default database. Use a disposable target or pass -AllowDefaultDatabase explicitly."
    }
    $sourceDatabase = [string]$manifest.database
    if ($TargetDatabase -eq $sourceDatabase) {
        throw "Refusing to restore into the source database name."
    }

    $postgresUser = [Environment]::GetEnvironmentVariable("KJDS_POSTGRES_USER")
    if (-not $postgresUser) {
        $postgresUser = "kjds"
    }
    Set-ScopedEnvironmentValue -Snapshot $restoredEnv -Name "KJDS_CUSTOMER_SCOPE_JSON" -Value $scopeInfo.canonical
    Set-ScopedEnvironmentValue -Snapshot $restoredEnv -Name "KJDS_DEPLOYMENT_NAME" -Value $ProjectName
    Set-ScopedEnvironmentValue -Snapshot $restoredEnv -Name "KJDS_DATABASE_NAME" -Value $defaultDatabase
    Set-ScopedEnvironmentValue -Snapshot $restoredEnv -Name "KJDS_POSTGRES_USER" -Value $postgresUser

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    Push-Location (Get-CommercialPilotRepoRoot)
    $locationPushed = $true

    & docker compose @composeArgs up -d postgres 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose could not start postgres."
    }
    Wait-ForPostgresHealthy -ComposeFile $ComposeFile -ProjectName $ProjectName -User $postgresUser -Database $defaultDatabase

    $containerId = (& docker compose @composeArgs ps -q postgres).Trim()
    if (-not $containerId) {
        throw "PostgreSQL container is not running."
    }
    $containerArchive = "/tmp/kjds-restore-$([guid]::NewGuid().ToString('N')).dump"

    try {
        & docker cp $archivePath "${containerId}:$containerArchive" 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not copy backup into PostgreSQL container."
        }
        & docker compose @composeArgs exec -T postgres psql -U $postgresUser -d postgres -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$TargetDatabase' AND pid <> pg_backend_pid();" 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not terminate target database sessions."
        }
        & docker compose @composeArgs exec -T postgres dropdb -U $postgresUser --if-exists $TargetDatabase 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not drop the disposable target database."
        }
        & docker compose @composeArgs exec -T postgres createdb -U $postgresUser $TargetDatabase 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create the disposable target database."
        }
        & docker compose @composeArgs exec -T postgres pg_restore -U $postgresUser --dbname=$TargetDatabase --no-owner --no-acl --exit-on-error $containerArchive 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "pg_restore failed."
        }
    } finally {
        & docker compose @composeArgs exec -T postgres rm -f $containerArchive 2>$null | Out-Null
    }

    $restoredHeadOutput = & docker compose @composeArgs exec -T postgres psql -U $postgresUser -d $TargetDatabase -Atc "SELECT version_num FROM alembic_version LIMIT 1;"
    if ($LASTEXITCODE -ne 0 -or -not $restoredHeadOutput) {
        throw "Could not read Alembic head from restored database."
    }
    $restoredHead = ([string]$restoredHeadOutput).Trim()
    if ($restoredHead -ne $manifest.alembic_head) {
        throw "Restored Alembic head '$restoredHead' does not match manifest '$($manifest.alembic_head)'."
    }

    $report = [ordered]@{
        status = "PASS"
        restored_at = (Get-Date).ToUniversalTime().ToString("o")
        elapsed_seconds = [math]::Round($stopwatch.Elapsed.TotalSeconds, 3)
        project_name = $ProjectName
        target_database = $TargetDatabase
        source_archive = $archivePath
        sha256 = $actualHash
        customer_scope_sha256 = $scopeInfo.sha256
        alembic_head = $restoredHead
    }
    $runtime = Join-Path (Get-CommercialPilotPackageRoot) "runtime"
    Ensure-Directory -Path $runtime
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runtime "RESTORE_VERIFICATION.json") -Encoding utf8
    $report | ConvertTo-Json -Depth 5
} finally {
    if ($locationPushed) {
        Pop-Location
    }
    Restore-ScopedEnvironment -Snapshot $restoredEnv
}
