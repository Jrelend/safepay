# Start the SafePay LOCAL DEMO (Docker Desktop must be installed).
#   powershell -ExecutionPolicy Bypass -File scripts\demo-start.ps1   (or double-click demo-start.cmd)
# Safe to run repeatedly: existing demo data is kept. Use demo-reset to start over.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example (local-only placeholder passwords)."
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker is not running. Start Docker Desktop, wait until it is ready, then run this again." -ForegroundColor Red
    exit 1
}

docker compose -f compose.yaml -f compose.demo.yaml up -d --build --wait
if ($LASTEXITCODE -ne 0) {
    Write-Host "The demo did not start. Logs: docker compose -f compose.yaml -f compose.demo.yaml logs" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "SafePay demo is running:  http://localhost:3000" -ForegroundColor Green
Write-Host "Use the yellow 'Demo' bar at the top to switch between Buyer, Seller and Admin."
Write-Host "DEMO - SIMULATED MONEY - NO REAL PAYMENTS"
