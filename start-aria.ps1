# ARIA one-click launcher.
#
# Double-click this file (or right-click -> Run with PowerShell). It starts
# everything and prints a QR CODE — point your phone camera at it and ARIA
# opens. No typing IP addresses, and it keeps working when your router
# changes the address.
#
# First time only: run allow-phone.ps1 once as Administrator.

$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
$api  = Join-Path $root "apps\api"
$web  = Join-Path $root "apps\web"

Write-Host ""
Write-Host "  Starting ARIA..." -ForegroundColor Cyan

# ── 1. Databases ──────────────────────────────────────────────────────────
Write-Host "  [1/4] Databases (Docker)..." -NoNewline
Push-Location $root
docker compose up -d 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host " ok" -ForegroundColor Green }
else { Write-Host " FAILED — is Docker Desktop running?" -ForegroundColor Red }
Pop-Location

# ── 2. API ────────────────────────────────────────────────────────────────
# --host 0.0.0.0 so the phone can reach it, not just this PC.
Write-Host "  [2/4] API server..." -NoNewline
Start-Process powershell -WindowStyle Minimized -ArgumentList '-NoExit', '-Command', `
  "cd '$api'; .\.venv\Scripts\Activate.ps1; uvicorn src.main:app --host 0.0.0.0 --port 8000"
Write-Host " starting" -ForegroundColor Green

# ── 3. Dashboard ──────────────────────────────────────────────────────────
Write-Host "  [3/4] Dashboard..." -NoNewline
Start-Process powershell -WindowStyle Minimized -ArgumentList '-NoExit', '-Command', `
  "cd '$web'; npm run dev -- -H 0.0.0.0 -p 3000"
Write-Host " starting" -ForegroundColor Green

# ── 4. Find this PC's address on the home network ────────────────────────
# Prefer real LAN ranges; skip Docker/WSL virtual adapters (172.16-31.x).
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

$phoneUrl = if ($ip) { "http://$($ip):3000" } else { $null }

# ── Wait until the dashboard actually answers ────────────────────────────
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

# ── QR code so the phone just works ──────────────────────────────────────
function Show-Qr($text) {
  # Rendered locally by the qrcode module if present; otherwise fall back to
  # printing the URL. We deliberately do NOT send the URL to a web service —
  # it would leak your private network address off the machine.
  if (Get-Module -ListAvailable -Name QRCodeGenerator) {
    try { Import-Module QRCodeGenerator -ErrorAction Stop; New-QRCodeText -Text $text -Show; return $true } catch { }
  }
  return $false
}

Write-Host ""
Write-Host "  ────────────────────────────────────────────────" -ForegroundColor DarkGray
if ($ready) { Write-Host "   ARIA is running." -ForegroundColor Green }
else { Write-Host "   ARIA is still starting (give it a few more seconds)." -ForegroundColor Yellow }
Write-Host ""
Write-Host "   On this PC:    " -NoNewline; Write-Host "http://localhost:3000" -ForegroundColor White
if ($phoneUrl) {
  Write-Host "   On your phone: " -NoNewline; Write-Host $phoneUrl -ForegroundColor Cyan
  # Write the URL to a file the dashboard can show as a scannable QR.
  Set-Content -Path (Join-Path $root "apps\web\public\phone-url.txt") -Value $phoneUrl -Encoding utf8 -NoNewline
  Write-Host ""
  Write-Host "   Scan the QR code at " -NoNewline -ForegroundColor DarkGray
  Write-Host "http://localhost:3000/connect" -ForegroundColor White -NoNewline
  Write-Host " with your phone camera." -ForegroundColor DarkGray
} else {
  Write-Host "   Phone access unavailable: no home-network address found." -ForegroundColor Yellow
  Write-Host "   Are you connected to Wi-Fi?" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "   Phone must be on the same Wi-Fi. First time only:" -ForegroundColor DarkGray
Write-Host "   run allow-phone.ps1 once as Administrator." -ForegroundColor DarkGray
Write-Host "  ────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host ""

if ($ready -and $phoneUrl) { Start-Process "http://localhost:3000/connect" }
