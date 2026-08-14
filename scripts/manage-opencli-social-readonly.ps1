[CmdletBinding()]
param(
    [ValidateSet("Setup", "Launch", "Doctor", "Plan", "Collect")]
    [string]$Mode = "Doctor",
    [ValidateSet("all", "douyin", "xiaohongshu")]
    [string]$Platform = "all",
    [string]$AwemeId,
    [string]$XhsNoteId
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$registryPath = Join-Path $repoRoot `
    "docs\project\registries\social_intelligence_read_allowlist.json"
$registry = Get-Content -LiteralPath $registryPath -Raw | ConvertFrom-Json
$runtimeRoot = [IO.Path]::GetFullPath(
    (Join-Path $repoRoot ".runtime\social-intelligence\opencli")
)
$extensionRoot = [IO.Path]::GetFullPath(
    (Join-Path $repoRoot $registry.browser_isolation.extension_path)
)
$profileRoot = [IO.Path]::GetFullPath(
    (Join-Path $repoRoot $registry.browser_isolation.profile_path)
)
$extensionArchive = "$extensionRoot.zip"

function Assert-PathInsideRuntime([string]$Path) {
    $resolved = [IO.Path]::GetFullPath($Path)
    $repoRuntime = [IO.Path]::GetFullPath((Join-Path $repoRoot ".runtime"))
    if (-not $resolved.StartsWith(
        $repoRuntime + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Runtime path escaped the repository runtime root: $resolved"
    }
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-OpenCliCommand {
    $command = Get-Command "opencli" -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "OpenCLI is not installed. Run -Mode Setup first."
    }
    return $command
}

function Get-DoctorResult {
    $openCli = Get-OpenCliCommand
    $lines = @(& $openCli.Source doctor -v 2>&1)
    $exitCode = $LASTEXITCODE
    $text = $lines -join [Environment]::NewLine
    return [ordered]@{
        exit_code = $exitCode
        daemon_ok = $text.Contains("[OK] Daemon:")
        extension_ok = $text.Contains("[OK] Extension:")
        connectivity_ok = $text.Contains("[OK] Connectivity:")
        literal_output = $text
    }
}

function Assert-ExtensionContract {
    $manifestPath = Join-Path $extensionRoot "manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw "OpenCLI extension is not installed at $extensionRoot"
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ([string]$manifest.version -ne [string]$registry.runtime.extension_version) {
        throw "OpenCLI extension version drift: $($manifest.version)"
    }
}

function Install-OpenCliRuntime {
    $npm = Get-Command "npm" -ErrorAction SilentlyContinue
    if (-not $npm) {
        throw "npm is required to install OpenCLI."
    }
    $package = "$($registry.runtime.package)@$($registry.runtime.cli_version)"
    & $npm.Source install --global $package
    if ($LASTEXITCODE -ne 0) {
        throw "npm failed to install $package"
    }

    Assert-PathInsideRuntime $extensionRoot
    Assert-PathInsideRuntime $extensionArchive
    $null = New-Item -ItemType Directory -Force -Path (Split-Path $extensionRoot)
    if (-not (Test-Path -LiteralPath $extensionArchive -PathType Leaf)) {
        $assetUrl = (
            $registry.runtime.release_url -replace "/tag/", "/download/"
        ) + "/" + $registry.runtime.extension_asset
        Invoke-WebRequest -UseBasicParsing -Uri $assetUrl -OutFile $extensionArchive
    }
    $actualDigest = Get-Sha256 $extensionArchive
    if ($actualDigest -ne $registry.runtime.extension_sha256) {
        throw "OpenCLI extension digest mismatch: $actualDigest"
    }
    if (-not (Test-Path -LiteralPath $extensionRoot)) {
        Expand-Archive -LiteralPath $extensionArchive -DestinationPath $extensionRoot
    }
    Assert-ExtensionContract

    $version = (& (Get-OpenCliCommand).Source --version).Trim()
    if ($LASTEXITCODE -ne 0 -or $version -ne $registry.runtime.cli_version) {
        throw "OpenCLI version drift: expected $($registry.runtime.cli_version), got $version"
    }
    [ordered]@{
        status = "installed"
        cli_version = $version
        extension_version = $registry.runtime.extension_version
        extension_sha256 = $actualDigest
        extension_root = $extensionRoot
        profile_root = $profileRoot
    } | ConvertTo-Json -Depth 4
}

function Find-ChromiumBrowser {
    $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    $candidates = @(
        (Join-Path $programFilesX86 "Microsoft\Edge\Application\msedge.exe"),
        (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe"),
        (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
        (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
    )
    $browser = $candidates |
        Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } |
        Select-Object -First 1
    if (-not $browser) {
        throw "A Chrome or Edge browser executable was not found."
    }
    return $browser
}

function Start-IsolatedBrowser {
    Assert-ExtensionContract
    Assert-PathInsideRuntime $profileRoot
    $null = New-Item -ItemType Directory -Force -Path $profileRoot
    $browser = Find-ChromiumBrowser
    $launchArguments = @(
        "--user-data-dir=$profileRoot",
        "--disable-extensions-except=$extensionRoot",
        "--load-extension=$extensionRoot",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window"
    )
    $selected = if ($Platform -eq "all") {
        @("douyin", "xiaohongshu")
    } else {
        @($Platform)
    }
    foreach ($name in $selected) {
        $launchArguments += [string]$registry.platforms.$name.login_url
    }
    $process = Start-Process -FilePath $browser `
        -ArgumentList $launchArguments -PassThru

    $deadline = (Get-Date).AddSeconds(30)
    do {
        Start-Sleep -Seconds 1
        try {
            $doctor = Get-DoctorResult
            if ($doctor.extension_ok -and $doctor.connectivity_ok) {
                [ordered]@{
                    status = "connected"
                    browser = $browser
                    launcher_pid = $process.Id
                    profile_root = $profileRoot
                    extension_root = $extensionRoot
                } | ConvertTo-Json -Depth 4
                return
            }
        } catch {
            # Keep polling until the bounded deadline.
        }
    } while ((Get-Date) -lt $deadline)
    throw "The isolated OpenCLI browser did not connect within 30 seconds."
}

function Get-SelectedPlatforms {
    if ($Platform -eq "all") {
        return @("douyin", "xiaohongshu")
    }
    return @($Platform)
}

function Get-CollectionPlan {
    $plan = @()
    foreach ($name in Get-SelectedPlatforms) {
        $platformContract = $registry.platforms.$name
        foreach ($command in $platformContract.commands) {
            $include = [bool]$command.baseline
            $positional = $null
            if ($command.required_input -eq "AwemeId" -and $AwemeId) {
                if ($AwemeId -notmatch "^[0-9]{6,32}$") {
                    throw "AwemeId must contain 6 to 32 decimal digits."
                }
                $include = $true
                $positional = $AwemeId
            }
            if ($command.required_input -eq "XhsNoteId" -and $XhsNoteId) {
                if ($XhsNoteId -notmatch "^[A-Za-z0-9_-]{6,128}$") {
                    throw "XhsNoteId has an invalid format."
                }
                $include = $true
                $positional = $XhsNoteId
            }
            if (-not $include) {
                continue
            }
            $arguments = @()
            if ($positional) {
                $arguments += $positional
            }
            $arguments += @($command.arguments)
            $plan += [ordered]@{
                platform = $name
                command = [string]$command.name
                domain = [string]$platformContract.domain
                arguments = $arguments
                access = "read"
                external_write = $false
            }
        }
    }
    return $plan
}

function Assert-CommandContract($Item) {
    $openCli = Get-OpenCliCommand
    $help = @(
        & $openCli.Source $Item.platform $Item.command --help -f yaml 2>&1
    ) -join [Environment]::NewLine
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect OpenCLI contract for $($Item.platform).$($Item.command)"
    }
    if ($help -notmatch "(?m)^access:\s*read\s*$") {
        throw "OpenCLI command is no longer read-only: $($Item.platform).$($Item.command)"
    }
    $expectedDomain = [Regex]::Escape([string]$Item.domain)
    if ($help -notmatch "(?m)^domain:\s*$expectedDomain\s*$") {
        throw "OpenCLI command domain drifted: $($Item.platform).$($Item.command)"
    }
}

function Invoke-Collection {
    $doctor = Get-DoctorResult
    if (-not ($doctor.daemon_ok -and $doctor.extension_ok -and $doctor.connectivity_ok)) {
        throw "OpenCLI browser bridge is not connected. Run -Mode Launch first."
    }
    $plan = @(Get-CollectionPlan)
    $runId = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ") + `
        "-" + [Guid]::NewGuid().ToString("N").Substring(0, 8)
    $runRoot = Join-Path $runtimeRoot $runId
    Assert-PathInsideRuntime $runRoot
    $null = New-Item -ItemType Directory -Force -Path $runRoot
    $openCli = Get-OpenCliCommand
    $records = @()
    $blockedPlatforms = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal
    )

    foreach ($item in $plan) {
        if ($blockedPlatforms.Contains($item.platform)) {
            continue
        }
        Assert-CommandContract $item
        $stem = "$($item.platform)-$($item.command)"
        $stdoutPath = Join-Path $runRoot "$stem.stdout.json"
        $stderrPath = Join-Path $runRoot "$stem.stderr.txt"
        $invocation = @($item.platform, $item.command) + @($item.arguments) + @(
            "--window", "background",
            "--site-session", "persistent",
            "--keep-tab", "false",
            "-f", "json"
        )
        $started = (Get-Date).ToUniversalTime()
        & $openCli.Source @invocation 1> $stdoutPath 2> $stderrPath
        $exitCode = $LASTEXITCODE
        $finished = (Get-Date).ToUniversalTime()
        $jsonValid = $false
        $loggedIn = $null
        if ((Get-Item -LiteralPath $stdoutPath).Length -gt 0) {
            try {
                $parsed = Get-Content -LiteralPath $stdoutPath -Raw |
                    ConvertFrom-Json
                $jsonValid = $true
                if ($item.command -eq "whoami") {
                    $loggedIn = [bool]$parsed.logged_in
                }
            } catch {
                $jsonValid = $false
            }
        }
        $outcome = if ($exitCode -eq 0 -and $jsonValid -and $loggedIn -ne $false) {
            "success"
        } elseif ($exitCode -eq 77 -or $loggedIn -eq $false) {
            "auth_required"
        } else {
            "failed"
        }
        if ($outcome -ne "success") {
            $null = $blockedPlatforms.Add($item.platform)
        }
        $records += [ordered]@{
            platform = $item.platform
            command = $item.command
            arguments = @($item.arguments)
            access = "read"
            external_write = $false
            started_at = $started.ToString("o")
            finished_at = $finished.ToString("o")
            exit_code = $exitCode
            outcome = $outcome
            stdout_json_valid = $jsonValid
            stdout_path = [IO.Path]::GetRelativePath($repoRoot, $stdoutPath)
            stdout_sha256 = Get-Sha256 $stdoutPath
            stderr_path = [IO.Path]::GetRelativePath($repoRoot, $stderrPath)
            stderr_sha256 = Get-Sha256 $stderrPath
        }
    }

    $status = if (@($records | Where-Object { $_.outcome -eq "failed" }).Count -gt 0) {
        "failed"
    } elseif (@($records | Where-Object { $_.outcome -eq "auth_required" }).Count -gt 0) {
        "auth_required"
    } else {
        "pass"
    }
    $manifest = [ordered]@{
        schema_version = "kjds-opencli-social-read-run-v1"
        run_id = $runId
        status = $status
        cli_version = $registry.runtime.cli_version
        extension_version = $registry.runtime.extension_version
        registry_path = [IO.Path]::GetRelativePath($repoRoot, $registryPath)
        records = $records
    }
    $manifestPath = Join-Path $runRoot "run.json"
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath `
        -Encoding utf8NoBOM
    $manifest | ConvertTo-Json -Depth 8
    if ($status -eq "auth_required") {
        exit 77
    }
    if ($status -eq "failed") {
        exit 1
    }
}

Assert-PathInsideRuntime $runtimeRoot
Assert-PathInsideRuntime $extensionRoot
Assert-PathInsideRuntime $profileRoot

switch ($Mode) {
    "Setup" { Install-OpenCliRuntime }
    "Launch" { Start-IsolatedBrowser }
    "Doctor" { Get-DoctorResult | ConvertTo-Json -Depth 4 }
    "Plan" {
        [ordered]@{
            schema_version = $registry.schema_version
            platform = $Platform
            commands = @(Get-CollectionPlan)
            deny_by_default = [bool]$registry.deny_by_default
            output_root = [IO.Path]::GetRelativePath($repoRoot, $runtimeRoot)
        } | ConvertTo-Json -Depth 8
    }
    "Collect" { Invoke-Collection }
}
