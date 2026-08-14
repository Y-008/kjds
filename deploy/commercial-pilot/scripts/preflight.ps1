[CmdletBinding()]
param(
    [string]$ComposeFile,
    [string]$ReportPath
)

. (Join-Path $PSScriptRoot "_common.ps1")

if (-not $ComposeFile) {
    $ComposeFile = Join-Path (Get-CommercialPilotPackageRoot) "compose.production.yaml"
}
if (-not $ReportPath) {
    $ReportPath = Join-Path (Join-Path (Get-CommercialPilotPackageRoot) "runtime") "preflight-report.json"
}
if (-not (Test-Path -LiteralPath $ComposeFile)) {
    throw "Compose file not found: $ComposeFile"
}

function New-TextFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Value
    )
    Set-Content -LiteralPath $Path -Value $Value -Encoding utf8 -NoNewline
    return (Resolve-Path -LiteralPath $Path).Path
}

function Add-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Status,
        [Parameter(Mandatory = $true)][string]$Detail
    )
    $script:checks += [ordered]@{
        name = $Name
        status = $Status
        detail = $Detail
    }
    Write-Output ("{0,-32} {1,-8} {2}" -f $Name, $Status, $Detail)
}

function Invoke-ComposeConfig {
    param([Parameter(Mandatory = $true)][string]$EnvFile)
    $output = & docker compose --env-file $EnvFile -f $ComposeFile config 2>&1
    return [ordered]@{
        exit_code = $LASTEXITCODE
        output = $output
    }
}

function Convert-ProcessOutputToText {
    param([AllowEmptyCollection()][object[]]$Output)
    return (($Output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine)
}

$packageRoot = Get-CommercialPilotPackageRoot
$runtimeRoot = Join-Path $packageRoot "runtime"
Ensure-Directory -Path $runtimeRoot
$caseRoot = Join-Path $runtimeRoot ("preflight-" + (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ"))
Ensure-Directory -Path $caseRoot
$secretRoot = Join-Path $caseRoot "secrets"
Ensure-Directory -Path $secretRoot
$scheduledBackupRoot = Join-Path $caseRoot "scheduled-backups"
Ensure-Directory -Path $scheduledBackupRoot

$tenantRef = "customer-a"
$storeRef = "store-001"
$scopeJson = ([ordered]@{
    tenant_ref = $tenantRef
    entity_ref = "ozon-store-001"
    store_ref = $storeRef
    max_sku = 500
    max_users = 3
} | ConvertTo-Json -Compress)
$databaseName = "kjds_pilot_preflight"
$postgresUser = "pilot"
$deploymentName = "kjds-commercial-pilot-preflight"
$projectName = "kjds-pilot-preflight"
$publicOrigin = "https://pilot.example.invalid"
$dbPassword = "pilot-dev-password-" + [guid]::NewGuid().ToString("N")
$databaseUrl = "postgresql+psycopg://$postgresUser`:$dbPassword@postgres:5432/$databaseName"
$operatorKey = "pilot-operator-key-" + [guid]::NewGuid().ToString("N")
$approverKey = "pilot-approver-key-" + [guid]::NewGuid().ToString("N")

$postgresPasswordFile = New-TextFile -Path (Join-Path $secretRoot "postgres-password.txt") -Value $dbPassword
$databaseUrlFile = New-TextFile -Path (Join-Path $secretRoot "database-url.txt") -Value $databaseUrl
$apiKeyFile = New-TextFile -Path (Join-Path $secretRoot "api-key.txt") -Value $operatorKey
$apiKeysJson = [ordered]@{}
$apiKeysJson[$operatorKey] = [ordered]@{
    actor = "production-operator"
    roles = @("operator")
    tenant = $tenantRef
    stores = @($storeRef)
}
$apiKeysJson[$approverKey] = [ordered]@{
    actor = "production-approver"
    roles = @("approver")
    tenant = $tenantRef
    stores = @($storeRef)
}
$apiKeysJsonFile = New-TextFile -Path (Join-Path $secretRoot "api-keys.json") -Value ($apiKeysJson | ConvertTo-Json -Compress -Depth 6)
$webBindings = [ordered]@{
    "11111111-1111-4111-8111-111111111111" = "production-operator"
    "22222222-2222-4222-8222-222222222222" = "production-approver"
}
$webBindingsFile = New-TextFile -Path (Join-Path $secretRoot "web-user-actors.json") -Value ($webBindings | ConvertTo-Json -Compress)
$channelLeaseKeyFile = New-TextFile -Path (Join-Path $secretRoot "channel-lease-signing-key.txt") -Value (([guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")).Substring(0, 64))
$supabaseUrlFile = New-TextFile -Path (Join-Path $secretRoot "next-public-supabase-url.txt") -Value "https://supabase.example.invalid"
$supabaseKeyFile = New-TextFile -Path (Join-Path $secretRoot "next-public-supabase-publishable-key.txt") -Value ("pilot-publishable-key-" + [guid]::NewGuid().ToString("N"))
$tlsCertFile = New-TextFile -Path (Join-Path $secretRoot "tls.crt") -Value ("runtime-certificate-placeholder-" + [guid]::NewGuid().ToString("N"))
$tlsKeyFile = New-TextFile -Path (Join-Path $secretRoot "tls.key") -Value ("runtime-key-placeholder-" + [guid]::NewGuid().ToString("N"))

function New-RehearsalEnvFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [AllowEmptyString()][string]$CustomerScope,
        [AllowEmptyString()][string]$ApiTenant
    )
    $backupDirectory = ($scheduledBackupRoot -replace '\\', '/')
    return New-TextFile -Path $Path -Value (@(
        "KJDS_DEPLOYMENT_NAME=$deploymentName"
        "KJDS_DATABASE_NAME=$databaseName"
        "KJDS_POSTGRES_USER=$postgresUser"
        "KJDS_CUSTOMER_SCOPE_JSON=$CustomerScope"
        "KJDS_API_TENANT=$ApiTenant"
        "KJDS_API_STORES=$storeRef"
        "KJDS_WEB_PUBLIC_ORIGIN=$publicOrigin"
        "KJDS_POSTGRES_PASSWORD_FILE=$postgresPasswordFile"
        "KJDS_DATABASE_URL_FILE=$databaseUrlFile"
        "KJDS_API_KEY_FILE=$apiKeyFile"
        "KJDS_API_KEYS_JSON_FILE=$apiKeysJsonFile"
        "KJDS_WEB_USER_ACTORS_JSON_FILE=$webBindingsFile"
        "KJDS_CHANNEL_LEASE_SIGNING_KEY_FILE=$channelLeaseKeyFile"
        "NEXT_PUBLIC_SUPABASE_URL_FILE=$supabaseUrlFile"
        "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY_FILE=$supabaseKeyFile"
        "KJDS_TLS_CERT_FILE=$tlsCertFile"
        "KJDS_TLS_KEY_FILE=$tlsKeyFile"
        "KJDS_API_ACTOR=production-operator"
        "KJDS_API_ROLES=operator"
        "KJDS_CHANNEL_LEASE_ISSUER=kjds-managed-store"
        "KJDS_CHANNEL_LEASE_KEY_ID=lease-kid-1"
        "KJDS_PILOT_RUN_LEASE_SECONDS=900"
        "KJDS_LIMITED_EXECUTION_ENABLED=false"
        "KJDS_OZON_EXECUTION_IDENTITY_REF=ozon-worker"
        "KJDS_BACKUP_DIRECTORY=$backupDirectory"
        "KJDS_BACKUP_INTERVAL_SECONDS=86400"
        "KJDS_BACKUP_RETENTION_DAYS=14"
        "KJDS_BACKUP_RUN_ONCE=false"
    ) -join [Environment]::NewLine)
}

$validEnvFile = New-RehearsalEnvFile -Path (Join-Path $caseRoot "commercial-pilot.env") -CustomerScope $scopeJson -ApiTenant $tenantRef
$blankScopeEnvFile = New-RehearsalEnvFile -Path (Join-Path $caseRoot "commercial-pilot.blank-scope.env") -CustomerScope "" -ApiTenant $tenantRef
$blankTenantEnvFile = New-RehearsalEnvFile -Path (Join-Path $caseRoot "commercial-pilot.blank-tenant.env") -CustomerScope $scopeJson -ApiTenant ""
$scopeFile = New-TextFile -Path (Join-Path $caseRoot "customer-scope.json") -Value $scopeJson
$composeText = Get-Content -LiteralPath $ComposeFile -Raw
$tlsTemplatePath = Join-Path (Join-Path $packageRoot "tls") "Caddyfile.template"
$tlsTemplateText = Get-Content -LiteralPath $tlsTemplatePath -Raw
$powerShellEngine = (Get-Process -Id $PID).Path
$script:checks = @()
$overall = "PASS"

try {
    if ($composeText -match 'POSTGRES_PASSWORD_FILE' -and
        $composeText -match 'KJDS_API_KEY_FILE' -and
        $composeText -match 'KJDS_TLS_CERT_FILE' -and
        $composeText -match '80:80' -and
        $composeText -match '443:443' -and
        $composeText -notmatch '3000:3000' -and
        $composeText -notmatch '8000:8000' -and
        $composeText -notmatch '5432:5432' -and
        $composeText -notmatch 'media-worker') {
        Add-Check -Name "compose_static" -Status "PASS" -Detail "file-backed secrets, edge-only ports, and no write-capable media worker"
    } else {
        Add-Check -Name "compose_static" -Status "MISS" -Detail "compose leaks a dev port, lacks a secret reference, or includes media worker"
        $overall = "PARTIAL"
    }

    if ($composeText -match 'KJDS_API_TENANT' -and
        $composeText -match 'KJDS_API_STORES' -and
        $composeText -match 'KJDS_WEB_USER_ACTORS_JSON' -and
        $composeText -match 'deployment identity scope mismatch' -and
        $composeText -match 'credential identity scope mismatch' -and
        $composeText -match 'customer scope must be canonical JSON') {
        Add-Check -Name "identity_scope_binding" -Status "PASS" -Detail "API and Web consume exact tenant/store credentials and API entrypoint verifies them"
    } else {
        Add-Check -Name "identity_scope_binding" -Status "MISS" -Detail "deployment does not fail closed on identity scope mismatch"
        $overall = "PARTIAL"
    }

    if ($tlsTemplateText -match '\{\$KJDS_WEB_PUBLIC_ORIGIN\}' -and
        $tlsTemplateText -match 'tls /run/secrets/kjds_tls_cert /run/secrets/kjds_tls_key' -and
        $tlsTemplateText -match 'reverse_proxy api:8000' -and
        $tlsTemplateText -match 'reverse_proxy web:3000' -and
        $tlsTemplateText -notmatch 'preload' -and
        $tlsTemplateText -notmatch 'includeSubDomains') {
        Add-Check -Name "tls_template" -Status "PASS" -Detail "TLS termination is file-backed without unapproved preload scope"
    } else {
        Add-Check -Name "tls_template" -Status "MISS" -Detail "TLS template is incomplete or overcommits HSTS scope"
        $overall = "PARTIAL"
    }

    $validRender = Invoke-ComposeConfig -EnvFile $validEnvFile
    if ($validRender.exit_code -eq 0 -and
        ($validRender.output -match 'edge:') -and
        ($validRender.output -match 'postgres:') -and
        ($validRender.output -match 'api:') -and
        ($validRender.output -match 'web:')) {
        Add-Check -Name "compose_render" -Status "PASS" -Detail "docker compose config rendered the production stack"
    } else {
        Add-Check -Name "compose_render" -Status "MISS" -Detail "docker compose config could not render the production stack"
        $overall = "PARTIAL"
    }

    $blankRender = Invoke-ComposeConfig -EnvFile $blankScopeEnvFile
    if ($blankRender.exit_code -ne 0 -and (Convert-ProcessOutputToText -Output $blankRender.output) -match 'KJDS_CUSTOMER_SCOPE_JSON') {
        Add-Check -Name "scope_fail_closed" -Status "PASS" -Detail "blank customer scope is rejected by compose interpolation"
    } else {
        Add-Check -Name "scope_fail_closed" -Status "MISS" -Detail "blank customer scope was accepted or rejected for the wrong reason"
        $overall = "PARTIAL"
    }

    $blankTenantRender = Invoke-ComposeConfig -EnvFile $blankTenantEnvFile
    if ($blankTenantRender.exit_code -ne 0 -and (Convert-ProcessOutputToText -Output $blankTenantRender.output) -match 'KJDS_API_TENANT') {
        Add-Check -Name "identity_fail_closed" -Status "PASS" -Detail "blank API tenant identity is rejected by compose interpolation"
    } else {
        Add-Check -Name "identity_fail_closed" -Status "MISS" -Detail "blank API tenant identity was accepted or rejected for the wrong reason"
        $overall = "PARTIAL"
    }

    & docker compose --env-file $validEnvFile -f $ComposeFile -p $projectName down -v --remove-orphans 2>&1 | Out-Null
    $apiStartOutput = & docker compose --env-file $validEnvFile -f $ComposeFile -p $projectName up -d --build --wait --wait-timeout 180 api 2>&1
    $apiStartExit = $LASTEXITCODE
    $canExerciseData = $false
    if ($apiStartExit -eq 0) {
        $headOutput = & docker compose --env-file $validEnvFile -f $ComposeFile -p $projectName exec -T postgres psql -U $postgresUser -d $databaseName -Atc "SELECT version_num FROM alembic_version LIMIT 1;" 2>&1
        if ($LASTEXITCODE -eq 0 -and ([string]$headOutput).Trim()) {
            Add-Check -Name "api_runtime_migration" -Status "PASS" -Detail "production API became healthy after migrating its isolated database"
            $canExerciseData = $true
        } else {
            Add-Check -Name "api_runtime_migration" -Status "MISS" -Detail "API started but the migration head could not be read"
            $overall = "PARTIAL"
        }
    } else {
        Add-Check -Name "api_runtime_migration" -Status "MISS" -Detail "production API did not build and become healthy"
        $overall = "PARTIAL"
    }

    if ($canExerciseData) {
        $scheduledOutput = & docker compose --env-file $validEnvFile -f $ComposeFile -p $projectName run --rm --no-deps -e KJDS_BACKUP_RUN_ONCE=true backup 2>&1
        $scheduledExit = $LASTEXITCODE
        $scheduledManifest = Get-ChildItem -LiteralPath $scheduledBackupRoot -Filter '*.dump.manifest.json' | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
        if ($scheduledExit -eq 0 -and $scheduledManifest) {
            $scheduledData = Get-Content -LiteralPath $scheduledManifest.FullName -Raw | ConvertFrom-Json
            $scheduledArchive = Join-Path $scheduledBackupRoot $scheduledData.archive
            $scheduledScope = Get-CustomerScopeInfo -JsonText $scopeJson
            if ((Test-Path -LiteralPath $scheduledArchive) -and
                (Get-Sha256 -Path $scheduledArchive) -eq $scheduledData.sha256 -and
                $scheduledData.customer_scope_sha256 -eq $scheduledScope.sha256 -and
                $scheduledData.alembic_head -eq ([string]$headOutput).Trim()) {
                Add-Check -Name "scheduled_backup_package" -Status "PASS" -Detail "one-shot sidecar produced a scope-bound archive and valid manifest"
            } else {
                Add-Check -Name "scheduled_backup_package" -Status "MISS" -Detail "sidecar archive did not match its scope, hash, or migration manifest"
                $overall = "PARTIAL"
            }
        } else {
            Add-Check -Name "scheduled_backup_package" -Status "MISS" -Detail "one-shot scheduled backup sidecar failed"
            $overall = "PARTIAL"
        }
    } else {
        Add-Check -Name "scheduled_backup_package" -Status "UNKNOWN" -Detail "not exercised because API migration rehearsal failed"
        $overall = "PARTIAL"
    }

    if ($canExerciseData) {
        $backupData = $null
        $backupResult = & $powerShellEngine -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "backup.ps1") -ProjectName $projectName -Database $databaseName -ComposeFile $ComposeFile -EnvFile $validEnvFile -OutputDirectory (Join-Path $caseRoot "backups") -CustomerScopeFile $scopeFile 2>&1
        $backupExit = $LASTEXITCODE
        if ($backupExit -eq 0 -and $backupResult) {
            $backupData = (Convert-ProcessOutputToText -Output $backupResult) | ConvertFrom-Json
            if ($backupData.status -eq "PASS" -and (Test-Path -LiteralPath $backupData.archive) -and (Test-Path -LiteralPath $backupData.manifest)) {
                Add-Check -Name "backup_manifest" -Status "PASS" -Detail "pg_dump archive and scope-bound manifest were created"
            } else {
                Add-Check -Name "backup_manifest" -Status "MISS" -Detail "backup did not emit a usable archive and manifest"
                $overall = "PARTIAL"
            }
        } else {
            Add-Check -Name "backup_manifest" -Status "MISS" -Detail "backup script failed"
            $overall = "PARTIAL"
        }

        if ($backupData -and $backupData.status -eq "PASS") {
            $guardOutput = & $powerShellEngine -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "restore.ps1") -ProjectName $projectName -BackupPath $backupData.archive -TargetDatabase $databaseName -ComposeFile $ComposeFile -EnvFile $validEnvFile -CustomerScopeFile $scopeFile 2>&1
            $guardExit = $LASTEXITCODE
            $guardText = Convert-ProcessOutputToText -Output $guardOutput
            if ($guardExit -ne 0 -and $guardText -match 'Refusing to replace the default database') {
                Add-Check -Name "restore_guard" -Status "PASS" -Detail "restore refused to overwrite the default/source database"
            } else {
                Add-Check -Name "restore_guard" -Status "MISS" -Detail "unsafe restore target was not rejected by the expected guard"
                $overall = "PARTIAL"
            }

            $restoreResult = & $powerShellEngine -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "restore.ps1") -ProjectName $projectName -BackupPath $backupData.archive -TargetDatabase "kjds_pilot_restore" -ComposeFile $ComposeFile -EnvFile $validEnvFile -CustomerScopeFile $scopeFile 2>&1
            $restoreExit = $LASTEXITCODE
            if ($restoreExit -eq 0 -and $restoreResult) {
                $restoreData = (Convert-ProcessOutputToText -Output $restoreResult) | ConvertFrom-Json
                if ($restoreData.status -eq "PASS" -and $restoreData.alembic_head -eq $backupData.alembic_head) {
                    Add-Check -Name "restore_drill" -Status "PASS" -Detail "disposable restore completed with the manifest Alembic head"
                } else {
                    Add-Check -Name "restore_drill" -Status "MISS" -Detail "restored database did not match the backup manifest"
                    $overall = "PARTIAL"
                }
            } else {
                Add-Check -Name "restore_drill" -Status "MISS" -Detail "restore script failed"
                $overall = "PARTIAL"
            }
        } else {
            Add-Check -Name "restore_guard" -Status "UNKNOWN" -Detail "not exercised because no valid backup was available"
            Add-Check -Name "restore_drill" -Status "UNKNOWN" -Detail "not exercised because no valid backup was available"
            $overall = "PARTIAL"
        }
    } else {
        Add-Check -Name "backup_manifest" -Status "UNKNOWN" -Detail "not exercised because API migration rehearsal failed"
        Add-Check -Name "restore_guard" -Status "UNKNOWN" -Detail "not exercised because API migration rehearsal failed"
        Add-Check -Name "restore_drill" -Status "UNKNOWN" -Detail "not exercised because API migration rehearsal failed"
        $overall = "PARTIAL"
    }
} catch {
    Add-Check -Name "preflight_runtime" -Status "MISS" -Detail ("unexpected preflight failure: " + $_.Exception.Message)
    $overall = "PARTIAL"
} finally {
    try {
        & docker compose --env-file $validEnvFile -f $ComposeFile -p $projectName down -v 2>&1 | Out-Null
    } catch {
        # Cleanup is best-effort; the report still records the rehearsal result.
    }
}

Add-Check -Name "production_backup_runtime" -Status "UNKNOWN" -Detail "continuous schedule, retention execution, monitoring, and off-host copy are not deployed"
Add-Check -Name "live_production_evidence" -Status "UNKNOWN" -Detail "hosted TLS, cross-customer negative isolation, and live RPO/RTO are unproven"
$overall = "PARTIAL"

$report = [ordered]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    compose_file = (Resolve-Path -LiteralPath $ComposeFile).Path
    artifact_root = (Resolve-Path -LiteralPath $caseRoot).Path
    overall = $overall
    checks = $script:checks
}
$reportDirectory = Split-Path -Parent $ReportPath
if ($reportDirectory) {
    Ensure-Directory -Path $reportDirectory
}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportPath -Encoding utf8
Write-Output ($report | ConvertTo-Json -Depth 8)

if ($script:checks | Where-Object { $_.status -ne "PASS" }) {
    exit 1
}
