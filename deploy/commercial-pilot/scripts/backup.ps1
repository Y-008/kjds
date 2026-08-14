[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectName,

    [Parameter(Mandatory = $true)]
    [string]$Database,

    [string]$ComposeFile,

    [string]$OutputDirectory,

    [string]$EnvFile,

    [string]$CustomerScopeJson,

    [string]$CustomerScopeFile
)

. (Join-Path $PSScriptRoot "_common.ps1")

if (-not $ComposeFile) {
    $ComposeFile = Join-Path (Get-CommercialPilotPackageRoot) "compose.production.yaml"
}
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path (Join-Path (Get-CommercialPilotPackageRoot) "runtime") "backups"
}
if (-not (Test-Path -LiteralPath $ComposeFile)) {
    throw "Compose file not found: $ComposeFile"
}
if ($ProjectName -notmatch '^[A-Za-z0-9_.-]+$') {
    throw "ProjectName must contain only letters, numbers, dot, underscore, or dash."
}
if ($Database -notmatch '^[A-Za-z0-9_]+$') {
    throw "Database must contain only letters, numbers, and underscores."
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

    $databaseName = $Database
    $configuredDatabase = [Environment]::GetEnvironmentVariable("KJDS_DATABASE_NAME")
    if ($configuredDatabase -and $configuredDatabase -ne $Database) {
        throw "KJDS_DATABASE_NAME ('$configuredDatabase') does not match -Database ('$Database')."
    }
    if ($configuredDatabase) {
        $databaseName = $configuredDatabase
    }
    $postgresUser = [Environment]::GetEnvironmentVariable("KJDS_POSTGRES_USER")
    if (-not $postgresUser) {
        $postgresUser = "kjds"
    }

    Set-ScopedEnvironmentValue -Snapshot $restoredEnv -Name "KJDS_CUSTOMER_SCOPE_JSON" -Value $scopeInfo.canonical
    Set-ScopedEnvironmentValue -Snapshot $restoredEnv -Name "KJDS_DEPLOYMENT_NAME" -Value $ProjectName
    Set-ScopedEnvironmentValue -Snapshot $restoredEnv -Name "KJDS_DATABASE_NAME" -Value $databaseName
    Set-ScopedEnvironmentValue -Snapshot $restoredEnv -Name "KJDS_POSTGRES_USER" -Value $postgresUser

    Ensure-Directory -Path $OutputDirectory
    Push-Location (Get-CommercialPilotRepoRoot)
    $locationPushed = $true

    & docker compose @composeArgs up -d postgres 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose could not start postgres."
    }
    Wait-ForPostgresHealthy -ComposeFile $ComposeFile -ProjectName $ProjectName -User $postgresUser -Database $databaseName

    $containerId = (& docker compose @composeArgs ps -q postgres).Trim()
    if (-not $containerId) {
        throw "PostgreSQL container is not running."
    }

    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $baseName = "kjds-$ProjectName-$databaseName-$stamp"
    $archivePath = Join-Path $OutputDirectory "$baseName.dump"
    $manifestPath = "$archivePath.manifest.json"
    $containerArchive = "/tmp/$baseName.dump"

    try {
        & docker compose @composeArgs exec -T postgres pg_dump -U $postgresUser --format=custom --no-owner --no-acl --dbname=$databaseName --file=$containerArchive 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "pg_dump failed."
        }
        & docker cp "${containerId}:$containerArchive" $archivePath 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not copy backup from PostgreSQL container."
        }
    } finally {
        & docker compose @composeArgs exec -T postgres rm -f $containerArchive 2>$null | Out-Null
    }

    $headOutput = & docker compose @composeArgs exec -T postgres psql -U $postgresUser -d $databaseName -Atc "SELECT version_num FROM alembic_version LIMIT 1;"
    if ($LASTEXITCODE -ne 0 -or -not $headOutput) {
        throw "Could not read Alembic head from backup source."
    }
    $head = ([string]$headOutput).Trim()
    if (-not $head) {
        throw "Alembic head is empty in backup source."
    }

    $hash = Get-Sha256 -Path $archivePath
    $bytes = (Get-Item -LiteralPath $archivePath).Length
    $manifest = [ordered]@{
        manifest_version = 1
        created_at = (Get-Date).ToUniversalTime().ToString("o")
        deployment_name = $ProjectName
        customer_scope_sha256 = $scopeInfo.sha256
        customer_scope_json = $scopeInfo.canonical
        database = $databaseName
        archive = (Split-Path -Leaf $archivePath)
        sha256 = $hash
        bytes = $bytes
        alembic_head = $head
        format = "pg_dump-custom"
    }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding utf8

    [ordered]@{
        status = "PASS"
        archive = (Resolve-Path -LiteralPath $archivePath).Path
        manifest = (Resolve-Path -LiteralPath $manifestPath).Path
        sha256 = $hash
        alembic_head = $head
        customer_scope_sha256 = $scopeInfo.sha256
        deployment_name = $ProjectName
    } | ConvertTo-Json -Depth 5
} finally {
    if ($locationPushed) {
        Pop-Location
    }
    Restore-ScopedEnvironment -Snapshot $restoredEnv
}
