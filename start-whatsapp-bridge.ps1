# Start the read-only WhatsApp bridge.
#
# First run: a QR code appears — scan it on your phone
#   WhatsApp -> Settings -> Linked Devices -> Link a Device
# After that it reconnects automatically and no QR is needed.
#
# This bridge CANNOT send messages. Verified mechanically on every start.

$bridge = Join-Path $PSScriptRoot "apps\wa-bridge"

if (-not (Test-Path (Join-Path $bridge "node_modules"))) {
  Write-Host "  Installing bridge dependencies (first run only)..." -ForegroundColor Cyan
  Push-Location $bridge; npm install; Pop-Location
}

if (-not (Test-Path (Join-Path $bridge "config.json"))) {
  Write-Host "  Missing config.json." -ForegroundColor Red
  Write-Host "  Copy config.example.json to config.json and set the secret" -ForegroundColor DarkGray
  Write-Host "  to OPENCLAW_INGEST_SECRET from ARIA's .env" -ForegroundColor DarkGray
  exit 1
}

# Warn if ARIA is not up: the bridge would receive messages and drop them.
try {
  Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop | Out-Null
  Write-Host "  ARIA API reachable." -ForegroundColor Green
} catch {
  Write-Host "  WARNING: ARIA API is not running — messages will be dropped." -ForegroundColor Yellow
  Write-Host "  Start it first with start-aria.ps1" -ForegroundColor DarkGray
}

Push-Location $bridge

# Prove read-only before every run. If someone added a send call, stop here.
Write-Host "  Verifying read-only..." -ForegroundColor Cyan
npm run --silent verify-readonly
if ($LASTEXITCODE -ne 0) {
  Write-Host "  ABORTING: the bridge is no longer read-only." -ForegroundColor Red
  Pop-Location
  exit 1
}

node index.js
Pop-Location
