$ErrorActionPreference = "Stop"
$launcher = Join-Path $PSScriptRoot "launcher.mjs"
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw "portable_launcher_missing" }
& node $launcher
exit $LASTEXITCODE
