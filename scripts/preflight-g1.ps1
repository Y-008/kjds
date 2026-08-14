param(
    [int]$PostgresPort = 5432,
    [int]$ApiPort = 8010,
    [int]$WebPort = 3010
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "== preflight G-1 =="

$dirty = git status --porcelain
if ($dirty) {
    Write-Warning "Worktree has uncommitted changes."
    git status --short
} else {
    Write-Host "worktree clean"
}

$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like '*verify-g1.ps1*' -and $_.ProcessId -ne $PID
}
if ($existing) {
    Write-Warning "Another verify-g1.ps1 process is already running:"
    $existing | Select-Object ProcessId, Name, CommandLine | Format-List
    Write-Output "PREFLIGHT_BLOCKED"
    exit 1
}

foreach ($port in @($ApiPort, $WebPort)) {
    $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($listeners) {
        Write-Warning "Port $port is already in use by PID(s): $($listeners.OwningProcess -join ',')"
    } else {
        Write-Host "port $port free"
    }
}

$pg = Get-NetTCPConnection -LocalPort $PostgresPort -State Listen -ErrorAction SilentlyContinue
if (-not $pg) {
    Write-Warning "Postgres port $PostgresPort is not listening."
} else {
    Write-Host "postgres port $PostgresPort listening"
}

Write-Host "preflight-g1 PASS"