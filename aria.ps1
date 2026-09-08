# ARIA command launcher.
#
# Every command in ARIA's docs used to be an absolute path into one
# particular home directory. That works on exactly one machine. Clone the
# repo anywhere else - a second PC, a different user, a different drive - and
# every documented command is wrong.
#
# This resolves its own location, so the docs can say ".\aria.ps1 <command>"
# and be true on any machine. Run it from the repo root:
#
#   .\aria.ps1 start        start the databases, API and dashboard
#   .\aria.ps1 remote       set up access from anywhere (Tailscale)
#   .\aria.ps1 phone        open the firewall for your home Wi-Fi (admin)
#   .\aria.ps1 bridge       receive WhatsApp messages (cannot send)
#   .\aria.ps1 send         deliver approved replies (prints a pairing QR)
#   .\aria.ps1 send -DryRun show what would be sent, send nothing
#   .\aria.ps1 qr           render a pairing QR big enough to scan
#   .\aria.ps1 test         backend test suite
#   .\aria.ps1 check        frontend lint and build
#   .\aria.ps1 status       what is running right now
#
# NOTE: pure ASCII on purpose. Windows PowerShell 5.1 reads BOM-less files as
# ANSI, so a UTF-8 dash or arrow becomes garbage and breaks parsing.

[CmdletBinding()]
param(
  [Parameter(Position = 0)]
  [string]$Command = "help",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root   = $PSScriptRoot
$api    = Join-Path $root "apps\api"
$web    = Join-Path $root "apps\web"
$bridge = Join-Path $root "apps\wa-bridge"
$python = Join-Path $api ".venv\Scripts\python.exe"

function Require-Python {
  if (-not (Test-Path $python)) {
    Write-Host "  No Python environment at $python" -ForegroundColor Red
    Write-Host "  Create it once:" -ForegroundColor DarkGray
    Write-Host "    cd apps\api" -ForegroundColor DarkGray
    Write-Host "    python -m venv .venv" -ForegroundColor DarkGray
    Write-Host "    .\.venv\Scripts\python.exe -m pip install -r requirements.txt" -ForegroundColor DarkGray
    exit 1
  }
}

switch ($Command.ToLower()) {

  "start"  { & (Join-Path $root "start-aria.ps1") }

  "remote" { & (Join-Path $root "setup-remote-access.ps1") }

  "phone"  { & (Join-Path $root "allow-phone.ps1") }

  "bridge" { & (Join-Path $root "start-whatsapp-bridge.ps1") }

  "send" {
    # The only process that can send. Started deliberately, never automatically.
    if ($DryRun) { node (Join-Path $bridge "sender.js") --dry-run }
    else         { node (Join-Path $bridge "sender.js") }
  }

  "qr" {
    Require-Python
    & $python (Join-Path $root "scripts\render-whatsapp-qr.py")
  }

  "test" {
    Require-Python
    Push-Location $api
    try { & $python -m pytest -q } finally { Pop-Location }
  }

  "check" {
    Push-Location $web
    try {
      npm run lint
      if ($LASTEXITCODE -ne 0) { throw "lint failed" }
      npm run build
    } finally { Pop-Location }
  }

  "status" {
    Write-Host ""
    Write-Host "  ARIA status" -ForegroundColor Cyan
    Write-Host "  -----------" -ForegroundColor DarkGray

    try {
      $ready = Invoke-RestMethod -Uri "http://127.0.0.1:8000/ready" -TimeoutSec 4
      Write-Host "  API        running" -ForegroundColor Green
      foreach ($name in $ready.checks.PSObject.Properties.Name) {
        $check = $ready.checks.$name
        $colour = "Green"
        if (-not $check.ok) { $colour = "Yellow" }
        Write-Host ("    {0,-12} {1}" -f $name, $check.detail) -ForegroundColor $colour
      }
    } catch {
      Write-Host "  API        not running   (.\aria.ps1 start)" -ForegroundColor Yellow
    }

    try {
      Invoke-WebRequest -Uri "http://127.0.0.1:3000" -TimeoutSec 4 -UseBasicParsing | Out-Null
      Write-Host "  Dashboard  running" -ForegroundColor Green
    } catch {
      Write-Host "  Dashboard  not running   (.\aria.ps1 start)" -ForegroundColor Yellow
    }

    $observer = Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" |
      Where-Object { $_.CommandLine -like "*wa-bridge*index.js*" }
    $sender = Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" |
      Where-Object { $_.CommandLine -like "*wa-bridge*sender.js*" }

    if ($observer) { Write-Host "  WhatsApp   receiving" -ForegroundColor Green }
    else { Write-Host "  WhatsApp   not receiving (.\aria.ps1 bridge)" -ForegroundColor Yellow }

    if ($sender) { Write-Host "  Sending    on" -ForegroundColor Green }
    else { Write-Host "  Sending    off           (.\aria.ps1 send)" -ForegroundColor DarkGray }

    # The address another PC or phone would use.
    try {
      $where = Invoke-RestMethod -Uri "http://127.0.0.1:8000/connect" -TimeoutSec 4
      Write-Host ""
      if ($where.tailscale_url) {
        Write-Host "  From anywhere:  $($where.tailscale_url)" -ForegroundColor Cyan
      } else {
        Write-Host "  From anywhere:  not set up   (.\aria.ps1 remote)" -ForegroundColor DarkGray
      }
      if ($where.phone_url) {
        Write-Host "  On this Wi-Fi:  $($where.phone_url)" -ForegroundColor White
      }
    } catch { }
    Write-Host ""
  }

  default {
    Write-Host ""
    Write-Host "  ARIA" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "    .\aria.ps1 start        databases, API and dashboard"
    Write-Host "    .\aria.ps1 status       what is running right now"
    Write-Host "    .\aria.ps1 remote       reach ARIA from another PC or phone"
    Write-Host "    .\aria.ps1 phone        open the firewall for home Wi-Fi (admin)"
    Write-Host "    .\aria.ps1 bridge       receive WhatsApp messages"
    Write-Host "    .\aria.ps1 send         deliver approved replies"
    Write-Host "    .\aria.ps1 send -DryRun show what would be sent, send nothing"
    Write-Host "    .\aria.ps1 qr           render a pairing QR big enough to scan"
    Write-Host "    .\aria.ps1 test         backend tests"
    Write-Host "    .\aria.ps1 check        frontend lint and build"
    Write-Host ""
  }
}
