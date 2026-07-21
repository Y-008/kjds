$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$uv = "C:\Users\Lunar\AppData\Local\hermes\bin\uv.exe"
$runtime = Join-Path $repo ".runtime\authority-radar"
$config = Join-Path $repo "docs\project\registries\authority_sources.json"
$database = Join-Path $runtime "authority_radar.sqlite"
$export = Join-Path $runtime "authority-radar-latest.md"
$health = Join-Path $runtime "authority-radar-health.json"

if (-not (Test-Path -LiteralPath $uv)) {
    throw "uv executable not found: $uv"
}

New-Item -ItemType Directory -Force -Path $runtime | Out-Null
& $uv run --project $repo python "$repo\scripts\authority_radar\collect.py" `
    --config $config `
    --database $database `
    --export $export `
    --health $health `
    --export-limit 20
exit $LASTEXITCODE
