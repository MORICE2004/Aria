# Run this ONCE, as Administrator, to let your phone reach ARIA over Wi-Fi.
# Right-click this file -> "Run with PowerShell" won't be elevated; instead:
#   1. Start menu -> type "PowerShell" -> right-click -> "Run as administrator"
#   2. Run:  cd C:\Users\MORICE\projects\aria ;  .\allow-phone.ps1
#
# It opens the Windows Firewall for ports 3000 (dashboard) and 8000 (API)
# on PRIVATE networks only (your home Wi-Fi) — not public networks.

$rules = @(
  @{ Name = "ARIA dashboard (3000)"; Port = 3000 },
  @{ Name = "ARIA API (8000)";       Port = 8000 }
)

foreach ($r in $rules) {
  # Remove any previous copy so re-running is safe.
  Get-NetFirewallRule -DisplayName $r.Name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
  New-NetFirewallRule -DisplayName $r.Name -Direction Inbound `
    -LocalPort $r.Port -Protocol TCP -Action Allow -Profile Private | Out-Null
  Write-Host "Opened port $($r.Port) for '$($r.Name)'" -ForegroundColor Green
}

Write-Host "`nDone. Your phone (on the same Wi-Fi) can now reach ARIA." -ForegroundColor Cyan
