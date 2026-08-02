[CmdletBinding()]
param(
    [ValidateSet("Setup", "Doctor", "LoginQr", "LoginBrowser", "Run", "Test")]
    [string]$Mode = "Doctor",
    [string]$CookieSource,
    [string]$PackageIndex = "https://mirrors.aliyun.com/pypi/simple",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArgs
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeRoot = [IO.Path]::GetFullPath(
    (Join-Path $repoRoot ".runtime\social-intelligence")
)
$toolRoot = [IO.Path]::GetFullPath(
    (Join-Path $runtimeRoot "tools\xiaohongshu-cli-0.6.4")
)
$profileRoot = [IO.Path]::GetFullPath(
    (Join-Path $runtimeRoot "profiles\xiaohongshu-cli")
)
$upstream = "https://github.com/jackwener/xiaohongshu-cli.git"
$expectedCommit = "4d63f3c0c85ccd9054fa8e96d7f761aaf2507449"
$camoufoxRelease = "152.0.4-beta.28"
$camoufoxDigest = "386fc2f41139685f9a1a9cef0d024bc041d899c315ea538d561171b5b282e57d"

if (-not $toolRoot.StartsWith($runtimeRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Tool path escaped the project runtime root: $toolRoot"
}

function Assert-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command is not available: $Name"
    }
}

function Assert-PinnedCheckout {
    if (-not (Test-Path -LiteralPath (Join-Path $toolRoot ".git"))) {
        throw "xiaohongshu-cli is not installed. Run this script with -Mode Setup."
    }
    $actual = (& git -C $toolRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $actual -ne $expectedCommit) {
        throw "xiaohongshu-cli checkout drifted: expected $expectedCommit, got $actual"
    }
}

function Set-IsolatedProfile {
    $null = New-Item -ItemType Directory -Path $profileRoot -Force
    $env:HOME = $profileRoot
    $env:USERPROFILE = $profileRoot
}

function Invoke-Xhs([string[]]$Arguments) {
    Assert-PinnedCheckout
    Set-IsolatedProfile
    $python = Join-Path $toolRoot ".venv\Scripts\python.exe"
    & $python -m xhs_cli @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "xiaohongshu-cli exited with code $LASTEXITCODE"
    }
}

function Install-CamoufoxRuntime([string]$Python) {
    try {
        & $Python -c `
            "from camoufox.pkgman import launch_path; print(launch_path())" *> $null
        if ($LASTEXITCODE -eq 0) {
            return
        }
    } catch {
        # Continue to the resumable install path.
    }

    Assert-Command "curl.exe"
    $downloadDirectory = Join-Path $runtimeRoot "downloads"
    $archive = Join-Path $downloadDirectory `
        "camoufox-$camoufoxRelease-win.x86_64.zip"
    $url = "https://github.com/daijro/camoufox/releases/download/v$camoufoxRelease/camoufox-$camoufoxRelease-win.x86_64.zip"
    $null = New-Item -ItemType Directory -Path $downloadDirectory -Force
    & curl.exe --location --fail --retry 50 --retry-delay 2 `
        --retry-all-errors --continue-at - --output $archive $url
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to download the Camoufox runtime with resume support"
    }
    $actualDigest = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
    if ($actualDigest -ne $camoufoxDigest) {
        throw "Camoufox archive digest mismatch: $actualDigest"
    }

    $installDirectory = (& $Python -c `
        "from camoufox.pkgman import INSTALL_DIR; print(INSTALL_DIR)").Trim()
    if ([string]::IsNullOrWhiteSpace($installDirectory)) {
        throw "Camoufox did not report an install directory"
    }
    if (Test-Path -LiteralPath $installDirectory) {
        $existing = @(Get-ChildItem -LiteralPath $installDirectory -Force)
        if ($existing.Count -gt 0) {
            throw "Invalid non-empty Camoufox directory requires operator cleanup: $installDirectory"
        }
    }
    $null = New-Item -ItemType Directory -Path $installDirectory -Force
    Expand-Archive -LiteralPath $archive -DestinationPath $installDirectory -Force
    & $Python -c `
        "from camoufox.__main__ import CamoufoxUpdate; CamoufoxUpdate().set_version()"
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to record the Camoufox runtime version"
    }
    & $Python -c `
        "from camoufox.pkgman import launch_path; print(launch_path())"
    if ($LASTEXITCODE -ne 0) {
        throw "Camoufox runtime verification failed"
    }
}

Assert-Command "git"
Assert-Command "uv"

switch ($Mode) {
    "Setup" {
        $null = New-Item -ItemType Directory -Path (Split-Path $toolRoot) -Force
        if (-not (Test-Path -LiteralPath $toolRoot)) {
            & git clone --filter=blob:none --no-checkout $upstream $toolRoot
            if ($LASTEXITCODE -ne 0) {
                throw "Unable to clone $upstream"
            }
            & git -C $toolRoot checkout --detach $expectedCommit
            if ($LASTEXITCODE -ne 0) {
                throw "Unable to checkout $expectedCommit"
            }
        }
        Assert-PinnedCheckout

        $env:UV_DEFAULT_INDEX = $PackageIndex
        $env:UV_HTTP_TIMEOUT = "300"
        $python = Join-Path $toolRoot ".venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $python)) {
            & uv venv --project $toolRoot
            if ($LASTEXITCODE -ne 0) {
                throw "Unable to prepare the isolated Python environment"
            }
        }

        # Upstream 0.6.4 omits editables from its editable-build requirements.
        & uv pip install --python $python `
            "hatchling==1.31.0" "editables==0.6" "pathspec==1.1.1"
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to install the pinned build shim"
        }
        $requirements = Join-Path $runtimeRoot `
            "xiaohongshu-cli-0.6.4.requirements.txt"
        & uv export --project $toolRoot --frozen --extra dev `
            --no-emit-project --no-hashes --format requirements-txt `
            --output-file $requirements
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to export the upstream locked dependency set"
        }
        & uv pip install --python $python --requirements $requirements
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to install the upstream locked dependency set"
        }
        & uv pip install --python $python --editable $toolRoot `
            --no-build-isolation --no-deps
        if ($LASTEXITCODE -ne 0) {
            throw "Unable to install xiaohongshu-cli dependencies"
        }
        Install-CamoufoxRuntime $python
        Invoke-Xhs @("--version")
    }
    "Doctor" {
        Assert-PinnedCheckout
        Set-IsolatedProfile
        $version = (& (Join-Path $toolRoot ".venv\Scripts\python.exe") `
            -m xhs_cli --version).Trim()
        if ($LASTEXITCODE -ne 0) {
            throw "xiaohongshu-cli doctor failed"
        }
        [ordered]@{
            status = "installed"
            version = $version
            commit = $expectedCommit
            tool_root = $toolRoot
            profile_root = $profileRoot
            authenticated = Test-Path -LiteralPath (
                Join-Path $profileRoot ".xiaohongshu-cli\cookies.json"
            )
        } | ConvertTo-Json
    }
    "LoginQr" {
        Invoke-Xhs @("--cookie-source", "kjds-qr-only", "login", "--qrcode")
    }
    "LoginBrowser" {
        if ([string]::IsNullOrWhiteSpace($CookieSource) -or $CookieSource -eq "auto") {
            throw "LoginBrowser requires an explicit -CookieSource."
        }
        Invoke-Xhs @("--cookie-source", $CookieSource, "login")
    }
    "Run" {
        if (-not $CliArgs -or $CliArgs.Count -eq 0) {
            throw "Run requires xhs command arguments via -CliArgs."
        }
        $arguments = @("--cookie-source", "kjds-qr-only") + $CliArgs
        Invoke-Xhs $arguments
    }
    "Test" {
        Assert-PinnedCheckout
        $testArguments = @(
            "-m", "pytest", "-q", "-p", "no:cacheprovider",
            "--basetemp", (Join-Path $runtimeRoot "pytest-xiaohongshu-cli")
        )
        if ($IsWindows) {
            # Upstream asserts Unix mode bits that Windows ACLs do not expose.
            $testArguments += @(
                "--deselect", "tests/test_cookies.py::TestSaveCookies::test_file_permissions",
                "--deselect", "tests/test_cookies.py::TestNoteIndexCache::test_index_file_permissions"
            )
        }
        Push-Location $toolRoot
        try {
            & (Join-Path $toolRoot ".venv\Scripts\python.exe") @testArguments
            if ($LASTEXITCODE -ne 0) {
                throw "xiaohongshu-cli upstream tests failed"
            }
        } finally {
            Pop-Location
        }
    }
}
