# Reach ARIA from another PC (or your phone) over Tailscale.
#
# WHY TAILSCALE, and not port-forwarding or a public tunnel:
#
# ARIA holds WhatsApp session credentials that can send messages as you, a
# memory of your personal life, and an API that can act on your behalf. Exposing
# that to the public internet - a forwarded port, an ngrok URL - means anyone who
# finds the address can knock on it, and the only thing standing between them and
# ARIA is one password. A tailnet is a private network between YOUR devices:
# nothing is published, there is no public address to find, and a machine that is
# not signed into your account cannot see ARIA at all.
#
# This does NOT deploy ARIA anywhere. She keeps running on this PC. The other
# machine reaches this one directly.
#
# Run from the repo root:  .\aria.ps1 remote
#
# NOTE: pure ASCII on purpose - see the note in aria.ps1.

$ErrorActionPreference = "Stop"

$TAILSCALE_EXE = "C:\Program Files\Tailscale\tailscale.exe"
# Tailscale hands out addresses from 100.64.0.0/10 (carrier-grade NAT space).
$TAILNET_CIDR = "100.64.0.0/10"

function Find-Tailscale {
  $cmd = Get-Command tailscale -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  if (Test-Path $TAILSCALE_EXE) { return $TAILSCALE_EXE }
  return $null
}

function Test-Elevated {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
}

Write-Host ""
Write-Host "  ARIA remote access" -ForegroundColor Cyan
Write-Host "  ------------------" -ForegroundColor DarkGray

# --- 1. Tailscale present? ------------------------------------------------
$ts = Find-Tailscale

if (-not $ts) {
  Write-Host "  [1/4] Tailscale is not installed." -ForegroundColor Yellow

  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "  winget is not available. Install Tailscale by hand:" -ForegroundColor Red
    Write-Host "    https://tailscale.com/download/windows" -ForegroundColor DarkGray
    Write-Host "  Then run this again." -ForegroundColor DarkGray
    exit 1
  }

  if (-not (Test-Elevated)) {
    # Installing needs admin. Ask for it once, here, rather than failing
    # halfway through with a permissions error.
    Write-Host "  Installing needs Administrator. Approving the prompt will" -ForegroundColor DarkGray
    Write-Host "  re-run this script elevated." -ForegroundColor DarkGray
    Start-Process powershell -Verb RunAs -ArgumentList `
      '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`""
    exit 0
  }

  Write-Host "  Installing Tailscale..." -ForegroundColor Cyan
  winget install --id Tailscale.Tailscale --silent `
    --accept-source-agreements --accept-package-agreements
  if ($LASTEXITCODE -ne 0) {
    Write-Host "  Install failed (winget exit $LASTEXITCODE)." -ForegroundColor Red
    Write-Host "  Install by hand: https://tailscale.com/download/windows" -ForegroundColor DarkGray
    exit 1
  }

  $ts = Find-Tailscale
  if (-not $ts) {
    Write-Host "  Installed, but tailscale.exe was not found." -ForegroundColor Yellow
    Write-Host "  Open a NEW PowerShell window and run this again." -ForegroundColor DarkGray
    exit 1
  }
} else {
  Write-Host "  [1/4] Tailscale installed." -ForegroundColor Green
}

# --- 2. Signed in? --------------------------------------------------------
# `tailscale ip -4` prints this machine's tailnet address, or fails when the
# machine is not signed in. That is the cheapest reliable liveness check.
$tailnetIp = $null
try { $tailnetIp = (& $ts ip -4 2>$null | Select-Object -First 1) } catch { }

if (-not $tailnetIp) {
  Write-Host "  [2/4] Not signed in yet." -ForegroundColor Yellow
  Write-Host "  A browser will open. Sign in with the SAME account you will use" -ForegroundColor DarkGray
  Write-Host "  on the other PC - that is what makes them one private network." -ForegroundColor DarkGray
  Write-Host ""
  & $ts up
  try { $tailnetIp = (& $ts ip -4 2>$null | Select-Object -First 1) } catch { }
  if (-not $tailnetIp) {
    Write-Host "  Still not signed in. Run 'tailscale up' and try again." -ForegroundColor Red
    exit 1
  }
}
Write-Host "  [2/4] Signed in. This PC is $tailnetIp on your tailnet." -ForegroundColor Green

# --- 3. Firewall ----------------------------------------------------------
# Scoped to the tailnet range rather than opened to the local network: the
# point of this setup is that only your own devices can reach ARIA.
$rules = @(
  @{ Name = "ARIA dashboard over Tailscale (3000)"; Port = 3000 },
  @{ Name = "ARIA API over Tailscale (8000)";       Port = 8000 }
)

if (Test-Elevated) {
  foreach ($r in $rules) {
    Get-NetFirewallRule -DisplayName $r.Name -ErrorAction SilentlyContinue |
      Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName $r.Name -Direction Inbound `
      -LocalPort $r.Port -Protocol TCP -Action Allow `
      -RemoteAddress $TAILNET_CIDR | Out-Null
  }
  Write-Host "  [3/4] Firewall open on 3000 and 8000, for tailnet devices only." -ForegroundColor Green
} else {
  $missing = $rules | Where-Object {
    -not (Get-NetFirewallRule -DisplayName $_.Name -ErrorAction SilentlyContinue)
  }
  if ($missing) {
    Write-Host "  [3/4] Firewall rules still needed (requires Administrator)." -ForegroundColor Yellow
    Write-Host "        Re-run this from an elevated PowerShell to add them." -ForegroundColor DarkGray
  } else {
    Write-Host "  [3/4] Firewall rules already in place." -ForegroundColor Green
  }
}

# --- 4. Is ARIA actually listening? ---------------------------------------
$apiUp = $false
try {
  Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -TimeoutSec 4 -UseBasicParsing | Out-Null
  $apiUp = $true
} catch { }

if ($apiUp) {
  Write-Host "  [4/4] ARIA is running." -ForegroundColor Green
} else {
  Write-Host "  [4/4] ARIA is not running - start it with .\aria.ps1 start" -ForegroundColor Yellow
}

# --- What to do on the other machine --------------------------------------
Write-Host ""
Write-Host "  ------------------------------------------------" -ForegroundColor DarkGray
Write-Host "   ARIA's address from any of your devices:" -ForegroundColor White
Write-Host ""
Write-Host "     http://$($tailnetIp):3000" -ForegroundColor Cyan
Write-Host ""
Write-Host "   On the OTHER PC (or phone), once:" -ForegroundColor White
Write-Host "     1. Install Tailscale: https://tailscale.com/download" -ForegroundColor DarkGray
Write-Host "     2. Sign in with the SAME account" -ForegroundColor DarkGray
Write-Host "     3. Open the address above" -ForegroundColor DarkGray
Write-Host ""
Write-Host "   This PC must be ON and running ARIA. Nothing is published to" -ForegroundColor DarkGray
Write-Host "   the internet - only devices signed into your account can reach it." -ForegroundColor DarkGray
Write-Host "  ------------------------------------------------" -ForegroundColor DarkGray
Write-Host ""

if (-not $env:ARIA_PASSWORD) {
  $envFile = Join-Path $PSScriptRoot ".env"
  $hasPassword = $false
  if (Test-Path $envFile) {
    $line = Select-String -Path $envFile -Pattern '^ARIA_PASSWORD=.+' -ErrorAction SilentlyContinue
    if ($line) { $hasPassword = $true }
  }
  if (-not $hasPassword) {
    Write-Host "  WARNING: ARIA_PASSWORD is not set in .env." -ForegroundColor Red
    Write-Host "  Set it before using ARIA off this machine - without it she" -ForegroundColor DarkGray
    Write-Host "  refuses to send autonomously, and anyone on your tailnet could" -ForegroundColor DarkGray
    Write-Host "  read your memory." -ForegroundColor DarkGray
    Write-Host ""
  }
}
