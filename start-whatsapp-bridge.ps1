# Start the read-only WhatsApp bridge.
#
# First run: a QR code appears. Scan it on your phone:
#   WhatsApp -> Settings -> Linked Devices -> Link a Device
# After that it reconnects automatically and no QR is needed.
#
# This bridge CANNOT send messages. That is verified before every start.
#
# NOTE: this file is deliberately pure ASCII. Windows PowerShell 5.1 reads
# BOM-less files as ANSI, so a UTF-8 dash or box character becomes garbage
# and breaks parsing. Keep it ASCII.

$bridge = Join-Path $PSScriptRoot "apps\wa-bridge"

if (-not (Test-Path (Join-Path $bridge "node_modules"))) {
  Write-Host "  Installing bridge dependencies (first run only)..." -ForegroundColor Cyan
  Push-Location $bridge
  npm install
  Pop-Location
}

if (-not (Test-Path (Join-Path $bridge "config.json"))) {
  Write-Host "  Missing config.json." -ForegroundColor Red
  Write-Host "  Copy config.example.json to config.json and set the secret" -ForegroundColor DarkGray
  Write-Host "  to OPENCLAW_INGEST_SECRET from ARIA's .env" -ForegroundColor DarkGray
  exit 1
}

# ARIA being down is no longer message loss: the bridge fsyncs every message
# to apps\wa-bridge\spool before the network call and replays it on restart.
# Still worth saying, because nothing will be processed until she is up.
try {
  Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop | Out-Null
  Write-Host "  ARIA API reachable." -ForegroundColor Green
} catch {
  Write-Host "  WARNING: ARIA API is not running." -ForegroundColor Yellow
  Write-Host "  Messages are held on disk and delivered when she starts;" -ForegroundColor DarkGray
  Write-Host "  nothing is lost, but nothing is processed either." -ForegroundColor DarkGray
  Write-Host "  Start her with start-aria.ps1" -ForegroundColor DarkGray
}

Push-Location $bridge

# Prove read-only before every run. If a send call was added, stop here.
Write-Host "  Verifying read-only..." -ForegroundColor Cyan
npm run --silent verify-readonly
if ($LASTEXITCODE -ne 0) {
  Write-Host "  ABORTING: the bridge is no longer read-only." -ForegroundColor Red
  Pop-Location
  exit 1
}

# Pairing needs a QR a phone will actually scan, and the terminal one on
# Windows often will not - the console font squashes it just enough that the
# camera refuses it. Pairing therefore took two terminals started in the right
# order, which is why it kept not happening. Start the renderer here instead.
# It watches for a code and opens a browser page only if one appears, so a
# device that is already linked sees nothing.
$python   = Join-Path $PSScriptRoot "apps\api\.venv\Scripts\python.exe"
$renderer = Join-Path $PSScriptRoot "scripts\render-whatsapp-qr.py"
$qr = $null
if ((Test-Path $python) -and (Test-Path $renderer)) {
  $qr = Start-Process -FilePath $python `
    -ArgumentList @($renderer, "--role", "observer") `
    -PassThru -WindowStyle Minimized
  Write-Host "  Watching for a pairing code. If one appears, a page opens." -ForegroundColor Cyan
} else {
  Write-Host "  QR renderer not found; pair from the terminal code." -ForegroundColor DarkGray
}

try {
  node index.js
} finally {
  # The watcher exists only for this run. Leaving it behind would keep a stale
  # code on screen after the bridge stopped.
  if ($qr -and -not $qr.HasExited) { Stop-Process -Id $qr.Id -Force }
  Pop-Location
}
