"""ARIA Database Restore Utility.

Safely restores an ARIA SQLite database from a chosen backup file or the latest backup.
Includes integrity verification and pre-restore safety snapshotting.

Usage:
  python scripts/restore_aria.py
  python scripts/restore_aria.py --file backups/aria_backup_20260910_120000.db
"""

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT_DIR / "backups"


def get_target_db_path() -> Path:
    env_path = ROOT_DIR / ".env"
    db_file = ROOT_DIR / "aria.db"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip()
                if "sqlite" in url:
                    clean_path = url.split(":///", 1)[-1].split("://", 1)[-1]
                    return Path(clean_path)
    return db_file


def verify_integrity(path: Path) -> bool:
    try:
        conn = sqlite3.connect(str(path))
        cur = conn.cursor()
        cur.execute("PRAGMA quick_check")
        res = cur.fetchone()[0]
        conn.close()
        return res == "ok"
    except Exception as exc:
        print(f"  Integrity check failed: {exc}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Restore ARIA database from backup.")
    parser.add_argument("--file", type=str, default="", help="Specific backup file path to restore")
    args = parser.parse_args()

    print("=== ARIA Database Restore Starting ===")
    if args.file:
        backup_file = Path(args.file)
        if not backup_file.is_absolute():
            backup_file = ROOT_DIR / backup_file
    else:
        # Pick the latest .db backup
        backups = sorted(BACKUP_DIR.glob("aria_backup_*.db"), key=os.path.getmtime, reverse=True)
        if not backups:
            print(f"  No backup files found in {BACKUP_DIR}")
            sys.exit(1)
        backup_file = backups[0]

    if not backup_file.exists():
        print(f"  Backup file does not exist: {backup_file}")
        sys.exit(1)

    print(f"  Selected backup: {backup_file.name}")
    print("  Verifying backup file integrity...")
    if not verify_integrity(backup_file):
        print("  ERROR: Backup file failed integrity check. Aborting restore.")
        sys.exit(1)
    print("  Backup file integrity verified: OK")

    target_db = get_target_db_path()
    if target_db.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        pre_restore = target_db.with_suffix(f".pre-restore_{stamp}.bak")
        print(f"  Creating pre-restore safety copy: {pre_restore.name}")
        shutil.copy2(target_db, pre_restore)

    print(f"  Restoring database to {target_db}...")
    source_conn = sqlite3.connect(str(backup_file))
    dest_conn = sqlite3.connect(str(target_db))
    source_conn.backup(dest_conn)
    dest_conn.close()
    source_conn.close()

    print("  Verifying restored database integrity...")
    if not verify_integrity(target_db):
        print("  ERROR: Restored database failed integrity check!")
        sys.exit(1)

    print("=== ARIA Database Restore Completed Successfully ===\n")


if __name__ == "__main__":
    main()
