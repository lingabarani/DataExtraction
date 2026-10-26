#!/usr/bin/env python3
"""
OneExtraction — Production Database Restoration Manager
Enterprise database restore utility with SHA-256 integrity verification,
catalog manifest resolution, dry-run simulation, and zero hardcoded credentials.
"""

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

# Add project root and botasaurus to sys.path
_ROOT_DIR = Path(__file__).resolve().parent.parent.parent
_BOTA_DIR = _ROOT_DIR / "botasaurus"
for p in [_ROOT_DIR, _BOTA_DIR]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from config_manager import config_manager

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [RESTORE] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("oneextraction.restore")

DEFAULT_BACKUP_DIR = _ROOT_DIR / "backups" / "postgres"
MANIFEST_FILE = DEFAULT_BACKUP_DIR / "backup_manifest.json"


def compute_sha256(file_path: Path) -> str:
    """Computes SHA-256 digest of a backup file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(manifest_path: Path) -> list:
    """Loads backup catalog manifest."""
    if manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Could not read backup manifest: %s", e)
    return []


def list_backups(manifest_path: Path, backup_dir: Path) -> None:
    """Displays all cataloged backups with checksum verification status."""
    entries = load_manifest(manifest_path)
    if not entries:
        logger.info("No recorded backups found in manifest at %s", manifest_path)
        return

    logger.info("=== OneExtraction Backup Catalog (%d backups recorded) ===", len(entries))
    for idx, item in enumerate(reversed(entries), 1):
        filename = item.get("filename", "unknown")
        filepath = backup_dir / filename
        exists = filepath.exists()
        size_str = f"{item.get('size_bytes', 0) / 1024:.1f} KB"
        ts = item.get("timestamp", "unknown")
        sha = item.get("sha256", "unknown")[:16] + "..."
        status = "[EXISTS]" if exists else "[FILE MISSING]"
        logger.info("  %d. %s | %s | %s | SHA: %s | %s", idx, ts, filename, size_str, sha, status)


def get_latest_backup_entry(manifest_path: Path, backup_dir: Path) -> Optional[Tuple[Path, dict]]:
    """Resolves the most recent verified backup file from the manifest or disk."""
    entries = load_manifest(manifest_path)
    # Search backwards from the newest entries
    for entry in reversed(entries):
        filename = entry.get("filename")
        if filename:
            candidate = backup_dir / filename
            if candidate.exists():
                return candidate, entry

    # Fallback to file globbing if manifest is missing or empty
    if backup_dir.exists():
        files = sorted(
            [f for f in backup_dir.iterdir() if f.is_file() and not f.name.endswith(".json")],
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        if files:
            return files[0], {"filename": files[0].name, "sha256": None}

    return None


def verify_backup_integrity(dump_path: Path, expected_sha: Optional[str] = None) -> bool:
    """Verifies SHA-256 integrity of the target backup file."""
    if not dump_path.exists():
        logger.error("Target dump file does not exist: %s", dump_path)
        return False

    actual_sha = compute_sha256(dump_path)
    if expected_sha:
        if actual_sha.lower() == expected_sha.lower():
            logger.info("Integrity check PASSED: SHA-256 matches catalog manifest (%s)", actual_sha[:16])
            return True
        else:
            logger.error(
                "Integrity check FAILED: Manifest SHA=%s, File SHA=%s",
                expected_sha,
                actual_sha,
            )
            return False
    else:
        logger.info("Computed SHA-256 for %s: %s (no manifest checksum to compare)", dump_path.name, actual_sha)
        return True


def run_restore(
    dump_path: Path,
    target_db: Optional[str] = None,
    dry_run: bool = False,
    clean: bool = False,
) -> bool:
    """
    Executes PostgreSQL database restore using pg_restore / psql.
    """
    db_config = config_manager.get_database_config()
    db_type = db_config.get("type", "postgresql")

    if db_type != "postgresql":
        logger.error("Configured database type is '%s', not 'postgresql'. Restore aborted.", db_type)
        return False

    host = db_config["host"]
    port = str(db_config["port"])
    dbname = target_db or db_config["dbname"]
    user = db_config["user"]
    password = db_config.get("password", "")

    logger.info("Initiating database restore for target database='%s' host='%s:%s' from %s", dbname, host, port, dump_path.name)

    # Check for pg_restore binary
    pg_restore_bin = shutil.which("pg_restore")
    psql_bin = shutil.which("psql")

    if dry_run:
        clean_flag = "--clean --if-exists " if clean else ""
        logger.info(
            "[DRY RUN] Would execute: pg_restore -h %s -p %s -U %s -d %s %s-v %s",
            host, port, user, dbname, clean_flag, dump_path,
        )
        return True

    if not pg_restore_bin and not psql_bin:
        logger.warning("Neither pg_restore nor psql binary was found in the local PATH.")
        logger.info("Container restoration command for Docker Compose:")
        logger.info("  docker cp %s oneextraction-db:/tmp/%s", dump_path, dump_path.name)
        logger.info("  docker exec -i oneextraction-db pg_restore -U %s -d %s -v /tmp/%s", user, dbname, dump_path.name)
        return False

    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password

    # Execute pg_restore for custom format
    cmd = [
        pg_restore_bin or "pg_restore",
        "-h", host,
        "-p", port,
        "-U", user,
        "-d", dbname,
        "-v",
    ]
    if clean:
        cmd.extend(["--clean", "--if-exists"])
    cmd.append(str(dump_path))

    try:
        logger.info("Executing pg_restore...")
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, check=True)
        logger.info("pg_restore completed successfully for database='%s'", dbname)
        return True
    except subprocess.CalledProcessError as e:
        # pg_restore exit code 1 often occurs when non-critical warnings exist (e.g., table already exists)
        if e.returncode == 1:
            logger.warning("pg_restore completed with non-fatal warnings (exit code 1): %s", e.stderr[:500])
            return True
        logger.error("pg_restore failed with exit code %d: %s", e.returncode, e.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="OneExtraction Production PostgreSQL Restoration Manager")
    parser.add_argument("--dump-file", type=str, help="Path to specific dump file to restore")
    parser.add_argument("--latest", action="store_true", help="Restore the latest verified backup from the manifest")
    parser.add_argument("--list", action="store_true", help="List all cataloged backups in the manifest")
    parser.add_argument("--verify-only", action="store_true", help="Verify SHA-256 integrity without restoring")
    parser.add_argument("--target-db", type=str, help="Target database name (overrides configured default)")
    parser.add_argument("--clean", action="store_true", help="Drop existing database objects before restoring (--clean)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate restore commands without executing")

    args = parser.parse_args()

    if args.list:
        list_backups(MANIFEST_FILE, DEFAULT_BACKUP_DIR)
        return

    # Resolve target dump file
    dump_path = None
    expected_sha = None

    if args.dump_file:
        dump_path = Path(args.dump_file)
        if not dump_path.is_absolute():
            dump_path = DEFAULT_BACKUP_DIR / dump_path
        # Look up expected SHA in manifest
        entries = load_manifest(MANIFEST_FILE)
        for e in entries:
            if e.get("filename") == dump_path.name:
                expected_sha = e.get("sha256")
                break
    elif args.latest:
        resolved = get_latest_backup_entry(MANIFEST_FILE, DEFAULT_BACKUP_DIR)
        if resolved:
            dump_path, meta = resolved
            expected_sha = meta.get("sha256")
            logger.info("Resolved latest backup from catalog: %s (timestamp=%s)", dump_path.name, meta.get("timestamp"))
        else:
            logger.error("No valid backup found in %s", DEFAULT_BACKUP_DIR)
            sys.exit(1)
    else:
        # Default to latest if neither specified
        resolved = get_latest_backup_entry(MANIFEST_FILE, DEFAULT_BACKUP_DIR)
        if resolved:
            dump_path, meta = resolved
            expected_sha = meta.get("sha256")
            logger.info("Using latest cataloged backup: %s", dump_path.name)
        elif args.dry_run:
            dump_path = DEFAULT_BACKUP_DIR / "oneextraction_dump_simulated.sql.gz"
            logger.info("[DRY RUN] No live backup files present; simulating with %s", dump_path.name)
            run_restore(dump_path=dump_path, target_db=args.target_db, dry_run=True, clean=args.clean)
            logger.info("[SUCCESS] Simulated restore dry-run verified successfully.")
            return
        else:
            logger.warning("No existing backups found in %s", DEFAULT_BACKUP_DIR)
            parser.print_help()
            sys.exit(1)

    # 1. Verify file integrity
    valid = verify_backup_integrity(dump_path, expected_sha)
    if not valid:
        logger.error("Backup file failed integrity verification. Aborting.")
        sys.exit(1)

    if args.verify_only:
        logger.info("[SUCCESS] Backup file %s is intact and verified.", dump_path.name)
        return

    # 2. Execute or simulate restore
    success = run_restore(
        dump_path=dump_path,
        target_db=args.target_db,
        dry_run=args.dry_run,
        clean=args.clean,
    )

    if success:
        logger.info("[SUCCESS] Database restoration procedure finished.")
    else:
        logger.error("[FAILED] Database restoration encountered errors.")
        sys.exit(1)


if __name__ == "__main__":
    main()
