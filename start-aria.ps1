# ARIA one-click launcher.
# Double-click this file (or: right-click -> Run with PowerShell) to start
# everything and print the link for your PC and your phone.
#
# Starts: the databases (Docker), the API, and the dashboard — the last two
# bound to 0.0.0.0 so your phone can reach them over Wi-Fi.

$root = $PSScriptRoot
$api  = Join-Path $root "apps\api"
$web  = Join-Path $root "apps\web"

Write-Host "Starting ARIA..." -ForegroundColor Cyan

# 1. Databases (Postgres + Redis) via Docker.
Push-Location $root
docker compose up -d | Out-Null
Pop-Location

# 2. API server, bound to all network interfaces, in its own window.
Start-Process powershell -ArgumentList '-NoExit', '-Command', `
  "cd '$api'; .\.venv\Scripts\Activate.ps1; uvicorn src.main:app --host 0.0.0.0 --port 8000"

# 3. Dashboard, bound to all interfaces, in its own window.
Start-Process powershell -ArgumentList '-NoExit', '-Command', `
  "cd '$web'; npm run dev -- -H 0.0.0.0 -p 3000"

# 4. Find this PC's home-network address (prefer 192.168.* / 10.*, skip
#    Docker/WSL virtual adapters in the 172.* range).
$ip = (Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -like '192.168.*' -or $_.IPAddress -like '10.*' } |
  Where-Object { $_.IPAddress -ne '127.0.0.1' } |
  Select-Object -First 1).IPAddress
if (-not $ip) { $ip = "<your-PC-IP>" }

Start-Sleep -Seconds 3
Write-Host "`n───────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host " ARIA is starting (give it ~15 seconds)." -ForegroundColor Green
Write-Host ""
Write-Host " On this PC:   http://localhost:3000" -ForegroundColor White
Write-Host " On your phone: http://$($ip):3000" -ForegroundColor Cyan
Write-Host ""
Write-Host " (Phone must be on the SAME Wi-Fi. Run allow-phone.ps1 once as" -ForegroundColor DarkGray
Write-Host "  admin first if the phone can't connect.)" -ForegroundColor DarkGray
Write-Host "───────────────────────────────────────────────" -ForegroundColor DarkGray
