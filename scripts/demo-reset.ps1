# Reset the SafePay LOCAL DEMO to a clean state: deletes ALL local SafePay data
# (the local Docker database volume), then starts the demo again with fresh seeded
# accounts and the buyer's 10,000,000 MNT simulated balance.
#   powershell -ExecutionPolicy Bypass -File scripts\demo-reset.ps1 [-Yes]   (or double-click demo-reset.cmd)
# The ledger is append-only by design, so a reset recreates the database instead of
# deleting rows. Only this machine's Docker stack is touched.
param([switch]$Yes)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not $Yes) {
    $answer = Read-Host "Delete all local SafePay demo data and start fresh? (y/N)"
    if ($answer -notmatch '^(y|yes)$') {
        Write-Host "Cancelled. Nothing was changed."
        exit 0
    }
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker is not running. Start Docker Desktop, wait until it is ready, then run this again." -ForegroundColor Red
    exit 1
}

docker compose -f compose.yaml -f compose.demo.yaml down --volumes --remove-orphans
if ($LASTEXITCODE -ne 0) { exit 1 }
& (Join-Path $PSScriptRoot "demo-start.ps1")
