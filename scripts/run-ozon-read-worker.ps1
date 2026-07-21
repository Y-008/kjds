param(
    [Parameter(Mandatory = $true)][string]$PilotId,
    [Parameter(Mandatory = $false)][string]$OfferId,
    [Parameter(Mandatory = $false)][string[]]$OfferIds,
    [Parameter(Mandatory = $false)][string]$Cursor,
    [int]$PageSize = 10,
    [Parameter(Mandatory = $true)][string]$IdempotencyKey,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$env:KJDS_READ_ONLY_PILOT_ID = $PilotId
$env:KJDS_READ_ONLY_OFFER_ID = $OfferId
$env:KJDS_READ_ONLY_OFFER_IDS = ($OfferIds -join ",")
$env:KJDS_READ_ONLY_CURSOR = $Cursor
$env:KJDS_READ_ONLY_PAGE_SIZE = [string]$PageSize
$env:KJDS_READ_ONLY_IDEMPOTENCY_KEY = $IdempotencyKey

# Docker Compose loads the ignored local .env without this script parsing or printing
# credentials. --no-deps keeps the offline preflight from starting the API or any
# other service. The Python preflight returns before constructing HTTP clients.
docker compose --profile read-only-pilot run --rm --no-deps ozon-read-worker `
    python -m apps.control_plane.ozon_read_worker --preflight
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
if (-not $Execute) {
    Write-Output "Offline preflight passed. Re-run with -Execute only after owner approval."
    exit 0
}

docker compose --profile read-only-pilot run --rm ozon-read-worker
