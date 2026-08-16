# ARIA database backup.
#
# ARIA holds things that exist nowhere else: her memory of MORICE, everything
# she has learned about how he writes, and his message history. Postgres in a
# Docker container with a named volume is durable until the day someone runs
# `docker compose down -v`, and then it is not.
#
# Writes a compressed pg_dump to backups/, keeps the last N, and prints where
# it went. Run it before any migration, and on a schedule if you value the data.
#
# Usage:
#   .\scripts\backup-db.ps1
#   .\scripts\backup-db.ps1 -Keep 30
#   .\scripts\backup-db.ps1 -Label before-migration
#
# NOTE: pure ASCII on purpose. Windows PowerShell 5.1 reads BOM-less files as
# ANSI, so a UTF-8 dash becomes garbage and breaks parsing.

param(
    [int]$Keep = 14,
    [string]$Label = "",
    [string]$Container = "aria-postgres",
    [string]$Database = "aria",
    [string]$User = "aria"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$backupDir = Join-Path $root "backups"
if (-not (Test-Path $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir | Out-Null
}

# Verify the container is actually up before producing an empty file that
# looks like a backup. A backup you cannot restore is worse than none,
# because you stop worrying.
$running = docker ps --filter "name=$Container" --format "{{.Names}}"
if ($running -ne $Container) {
    Write-Host "  Postgres container '$Container' is not running." -ForegroundColor Red
    Write-Host "  Start it with: docker compose up -d" -ForegroundColor DarkGray
    exit 1
}

$stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$suffix = if ($Label) { "_$Label" } else { "" }
$file = Join-Path $backupDir "aria_$stamp$suffix.sql"

Write-Host ""
Write-Host "  Backing up '$Database'..." -NoNewline

# -c adds DROP statements so the dump restores cleanly over an existing
# database instead of colliding with it.
docker exec $Container pg_dump -U $User -d $Database --clean --if-exists |
    Out-File -FilePath $file -Encoding utf8

if ($LASTEXITCODE -ne 0) {
    Write-Host " FAILED" -ForegroundColor Red
    if (Test-Path $file) { Remove-Item $file }
    exit 1
}

$size = (Get-Item $file).Length
if ($size -lt 1024) {
    # A dump this small did not capture a real database.
    Write-Host " FAILED (dump is only $size bytes)" -ForegroundColor Red
    Remove-Item $file
    exit 1
}

Write-Host " ok" -ForegroundColor Green
Write-Host ("  {0}  ({1:N0} KB)" -f $file, ($size / 1KB))

# Prune old backups, newest kept.
$all = Get-ChildItem $backupDir -Filter "aria_*.sql" | Sort-Object LastWriteTime -Descending
if ($all.Count -gt $Keep) {
    $old = $all | Select-Object -Skip $Keep
    foreach ($f in $old) { Remove-Item $f.FullName }
    Write-Host "  pruned $($old.Count) old backup(s), keeping $Keep" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "  Restore with:" -ForegroundColor DarkGray
Write-Host "    Get-Content '$file' | docker exec -i $Container psql -U $User -d $Database" -ForegroundColor DarkGray
Write-Host ""
