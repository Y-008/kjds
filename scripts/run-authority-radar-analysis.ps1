$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$uv = "C:\Users\Lunar\AppData\Local\hermes\bin\uv.exe"
$runtime = Join-Path $repo ".runtime\authority-radar"

& $uv run --project $repo python -m scripts.authority_radar.analyze `
    --health "$runtime\authority-radar-health.json" `
    --events "$runtime\authority-radar-latest.md" `
    --output "$runtime\authority-radar-analysis-local.md" `
    --mirror "D:\AI\Apps\OpenClaw\workspace-chief\memory\authority-radar-latest.md" `
    --rejected "$runtime\rejected\authority-radar-candidate-latest.md" `
    --stdout
exit $LASTEXITCODE
