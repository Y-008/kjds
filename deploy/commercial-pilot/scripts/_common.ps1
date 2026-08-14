Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-CommercialPilotPackageRoot {
    return Split-Path -Parent $PSScriptRoot
}

function Get-CommercialPilotDeployRoot {
    return Split-Path -Parent (Get-CommercialPilotPackageRoot)
}

function Get-CommercialPilotRepoRoot {
    return Split-Path -Parent (Get-CommercialPilotDeployRoot)
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
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

function Get-Sha256Text {
    param([Parameter(Mandatory = $true)][string]$Text)

    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Get-CanonicalJsonText {
    param([Parameter(Mandatory = $true)][string]$JsonText)
    try {
        return ($JsonText | ConvertFrom-Json | ConvertTo-Json -Compress -Depth 32)
    } catch {
        throw "Invalid JSON payload: $($_.Exception.Message)"
    }
}

function Get-TextFromFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    $resolved = Resolve-Path -LiteralPath $Path
    return (Get-Content -LiteralPath $resolved.Path -Raw).Trim()
}

function Get-TextFromEnvOrFile {
    param(
        [Parameter(Mandatory = $true)][string]$ValueName,
        [string]$FileName = "$ValueName`_FILE"
    )

    $value = [Environment]::GetEnvironmentVariable($ValueName)
    if ($value) {
        return $value.Trim()
    }
    $filePath = [Environment]::GetEnvironmentVariable($FileName)
    if ($filePath) {
        return Get-TextFromFile -Path $filePath
    }
    return $null
}

function Import-DotEnvFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Environment file not found: $Path"
    }

    $values = [ordered]@{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $parts = $line -split "=", 2
        $name = $parts[0].Trim()
        if ($parts.Count -ne 2 -or $name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
            throw "Invalid environment assignment in '$Path': $line"
        }
        if ($values.Contains($name)) {
            throw "Duplicate environment variable '$name' in '$Path'."
        }
        $values[$name] = $parts[1]
    }
    return $values
}

function Set-ScopedEnvironmentValue {
    param(
        [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Snapshot,
        [Parameter(Mandatory = $true)][string]$Name,
        [AllowEmptyString()][string]$Value
    )

    if (-not $Snapshot.Contains($Name)) {
        $Snapshot[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
    }
    [Environment]::SetEnvironmentVariable($Name, $Value, "Process")
}

function Restore-ScopedEnvironment {
    param([Parameter(Mandatory = $true)][System.Collections.IDictionary]$Snapshot)

    foreach ($entry in $Snapshot.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "Process")
    }
}

function Assert-RequiredString {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )
    if (-not $Value -or -not $Value.Trim()) {
        throw "$Name must be non-empty"
    }
    return $Value.Trim()
}

function Get-CustomerScopeInfo {
    param([Parameter(Mandatory = $true)][string]$JsonText)

    $canonical = Get-CanonicalJsonText -JsonText $JsonText
    $scope = $canonical | ConvertFrom-Json
    foreach ($field in @("tenant_ref", "entity_ref", "store_ref")) {
        $value = [string]$scope.$field
        if (-not $value -or -not $value.Trim()) {
            throw "Customer scope field '$field' must be non-empty"
        }
        $normalized = $value.Trim().ToLowerInvariant()
        if ($normalized -match '^(default|sample|placeholder|todo|tbd|replace-me)$') {
            throw "Customer scope field '$field' must not use a placeholder value"
        }
    }
    if ($scope.PSObject.Properties.Name -contains "max_sku") {
        $maxSku = [int]$scope.max_sku
        if ($maxSku -lt 1 -or $maxSku -gt 500) {
            throw "Customer scope max_sku must be between 1 and 500"
        }
    }
    if ($scope.PSObject.Properties.Name -contains "max_users") {
        $maxUsers = [int]$scope.max_users
        if ($maxUsers -lt 1 -or $maxUsers -gt 3) {
            throw "Customer scope max_users must be between 1 and 3"
        }
    }
    return [ordered]@{
        canonical = $canonical
        sha256 = (Get-Sha256Text -Text $canonical)
        scope = $scope
    }
}

function Invoke-Compose {
    param(
        [Parameter(Mandatory = $true)][string]$ComposeFile,
        [Parameter(Mandatory = $true)][string]$ProjectName,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )
    & docker compose -f $ComposeFile -p $ProjectName @Arguments
    return $LASTEXITCODE
}

function Wait-ForPostgresHealthy {
    param(
        [Parameter(Mandatory = $true)][string]$ComposeFile,
        [Parameter(Mandatory = $true)][string]$ProjectName,
        [Parameter(Mandatory = $true)][string]$User,
        [Parameter(Mandatory = $true)][string]$Database,
        [int]$TimeoutSeconds = 90
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        & docker compose -f $ComposeFile -p $ProjectName exec -T postgres pg_isready -U $User -d $Database *> $null
        if ($LASTEXITCODE -eq 0) {
            return
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "PostgreSQL did not become healthy within $TimeoutSeconds seconds."
}

function Ensure-Directory {
    param([Parameter(Mandatory = $true)][string]$Path)
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}
