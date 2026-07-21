param(
    [int]$Limit = 20,
    [string]$Providers = "local,zhipu",
    [int]$MinEvaluated = 20,
    [double]$MinPassRate = 0.90
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$uv = "C:\Users\Lunar\AppData\Local\hermes\bin\uv.exe"
$runtime = Join-Path $repo ".runtime\authority-radar\evaluation"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

& $uv run --project $repo python -m scripts.authority_radar.evaluate `
    --dataset "$repo\docs\project\registries\authority_eval_gold.json" `
    --providers $Providers `
    --limit $Limit `
    --min-evaluated $MinEvaluated `
    --min-pass-rate $MinPassRate `
    --output-json "$runtime\latest.json" `
    --output-md "$runtime\latest.md"
exit $LASTEXITCODE
