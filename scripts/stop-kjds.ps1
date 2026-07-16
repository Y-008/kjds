$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot

foreach ($name in @("api", "web")) {
    $pidFile = Join-Path $Root ".runtime\$name.pid"
    if (Test-Path $pidFile) {
        $processId = [int](Get-Content $pidFile)
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($process) { Stop-Process -Id $processId -Force }
        Remove-Item $pidFile -Force
    }
}

Write-Output "KJDS web and API stopped. Shared AI tools remain available."
