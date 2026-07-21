$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
$uv = "C:\Users\Lunar\AppData\Local\hermes\bin\uv.exe"
$runtime = Join-Path $repo ".runtime\authority-radar"

& $uv run --project $repo python -m scripts.authority_radar.report `
    --database "$runtime\authority_radar.sqlite" `
    --output "$runtime\morning-readiness.md" `
    --mirror "D:\AI\Apps\OpenClaw\workspace-chief\memory\authority-radar-readiness.md" `
    --stdout
exit $LASTEXITCODE
