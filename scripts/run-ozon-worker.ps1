param(
    [Parameter(Mandatory = $true)][string]$CommandId,
    [Parameter(Mandatory = $true)][string]$OfferId,
    [Parameter(Mandatory = $true)][string[]]$EvidenceIds,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$env:KJDS_EXECUTION_COMMAND_ID = $CommandId
$env:KJDS_EXECUTION_OFFER_ID = $OfferId
$env:KJDS_EXECUTION_EVIDENCE_IDS = ($EvidenceIds -join ",")

# Compose loads ignored local credentials. --no-deps guarantees that preflight
# cannot start the API or any other network-capable process.
docker compose --profile live-execution run --rm --no-deps ozon-worker `
    python -m apps.control_plane.ozon_worker --preflight
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
if (-not $Execute) {
    Write-Output "Offline preflight passed. Re-run with -Execute only after owner approval."
    exit 0
}

docker compose --profile live-execution run --rm ozon-worker
