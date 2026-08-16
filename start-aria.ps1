# ARIA one-click launcher.
#
# Double-click this file (or right-click -> Run with PowerShell). It starts
# everything and opens a page with a QR CODE. Point your phone camera at it
# and ARIA opens. No typing IP addresses, and it keeps working when your
# router changes the address.
#
# First time only: run allow-phone.ps1 once as Administrator.
#
# NOTE: this file is deliberately pure ASCII. Windows PowerShell 5.1 reads
# BOM-less files as ANSI, so a UTF-8 dash or box character becomes garbage
# and breaks parsing. Keep it ASCII.

$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
$api  = Join-Path $root "apps\api"
$web  = Join-Path $root "apps\web"

Write-Host ""
Write-Host "  Starting ARIA..." -ForegroundColor Cyan

# --- 1. Databases --------------------------------------------------------
Write-Host "  [1/4] Databases (Docker)..." -NoNewline
Push-Location $root
docker compose up -d 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host " ok" -ForegroundColor Green }
else { Write-Host " FAILED - is Docker Desktop running?" -ForegroundColor Red }
Pop-Location

# --- 2. API --------------------------------------------------------------
# --host 0.0.0.0 so the phone can reach it, not just this PC.
Write-Host "  [2/4] API server..." -NoNewline
Start-Process powershell -WindowStyle Minimized -ArgumentList '-NoExit', '-Command', `
  "cd '$api'; .\.venv\Scripts\Activate.ps1; uvicorn src.main:app --host 0.0.0.0 --port 8000"
Write-Host " starting" -ForegroundColor Green

# --- 3. Dashboard --------------------------------------------------------
Write-Host "  [3/4] Dashboard..." -NoNewline
Start-Process powershell -WindowStyle Minimized -ArgumentList '-NoExit', '-Command', `
  "cd '$web'; npm run dev -- -H 0.0.0.0 -p 3000"
Write-Host " starting" -ForegroundColor Green

# --- 4. Find this PC's address on the home network -----------------------
# Prefer real LAN ranges; skip Docker/WSL virtual adapters.
Write-Host "  [4/4] Finding your network address..." -NoNewline
$ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
  Where-Object {
    ($_.IPAddress -like '192.168.*' -or $_.IPAddress -like '10.*') -and
    $_.IPAddress -ne '127.0.0.1' -and
    $_.InterfaceAlias -notmatch 'WSL|Docker|Hyper-V|Loopback'
  } |
  Sort-Object -Property InterfaceMetric |
  Select-Object -First 1).IPAddress

if (-not $ip) { Write-Host " not found" -ForegroundColor Yellow }
else { Write-Host " $ip" -ForegroundColor Green }

# --- Wait until the dashboard actually answers ---------------------------
Write-Host ""
Write-Host "  Waiting for ARIA to come up" -NoNewline
$ready = $false
foreach ($i in 1..40) {
  try {
    $r = Invoke-WebRequest -Uri "http://localhost:3000" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
    if ($r.StatusCode -eq 200) { $ready = $true; break }
  } catch { }
  Write-Host "." -NoNewline
  Start-Sleep -Seconds 2
}
Write-Host ""

Write-Host ""
Write-Host "  ------------------------------------------------" -ForegroundColor DarkGray
if ($ready) { Write-Host "   ARIA is running." -ForegroundColor Green }
else { Write-Host "   ARIA is still starting (give it a few more seconds)." -ForegroundColor Yellow }
Write-Host ""
Write-Host "   On this PC:    " -NoNewline
Write-Host "http://localhost:3000" -ForegroundColor White
if ($ip) {
  Write-Host "   On your phone: " -NoNewline
  Write-Host "http://$($ip):3000" -ForegroundColor Cyan
  Write-Host ""
  Write-Host "   Or scan the QR code at http://localhost:3000/connect" -ForegroundColor DarkGray
} else {
  Write-Host "   Phone access unavailable: no home-network address found." -ForegroundColor Yellow
  Write-Host "   Are you connected to Wi-Fi?" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "   Phone must be on the same Wi-Fi. First time only:" -ForegroundColor DarkGray
Write-Host "   run allow-phone.ps1 once as Administrator." -ForegroundColor DarkGray
Write-Host "  ------------------------------------------------" -ForegroundColor DarkGray
Write-Host ""

if ($ready -and $ip) { Start-Process "http://localhost:3000/connect" }
