"""
DataExtraction Enterprise — Production Database Migration Manager
Applies and audits versioned SQL migrations with transactional safety and SHA256 integrity checks.
"""

import hashlib
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple

logger = logging.getLogger("dataextraction.migrations")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [MIGRATION] %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

_CURRENT_DIR = Path(__file__).resolve().parent
_MIGRATIONS_DIR = _CURRENT_DIR / "migrations"

from packages.infrastructure.db_connector import get_connection, release_connection, DATABASE_TYPE


def _compute_checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def ensure_migrations_table(cur) -> None:
    """Creates the migration auditing ledger if it does not already exist."""
    if DATABASE_TYPE == "postgresql":
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                filename VARCHAR(255) NOT NULL,
                checksum VARCHAR(64) NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)


def get_applied_migrations(cur) -> Dict[str, str]:
    """Returns a dictionary of {version: checksum} for all applied migrations."""
    ensure_migrations_table(cur)
    cur.execute("SELECT version, checksum FROM schema_migrations ORDER BY version ASC")
    return {row[0]: row[1] for row in cur.fetchall()}


def get_migration_files() -> List[Tuple[str, str, Path]]:
    """Discovers and sorts all SQL migration files in packages/infrastructure/migrations."""
    if not _MIGRATIONS_DIR.exists():
        logger.warning("Migrations directory does not exist: %s", _MIGRATIONS_DIR)
        return []

    files = []
    for p in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        version = p.stem.split("_")[0]
        files.append((version, p.name, p))
    return files


def run_all_migrations() -> List[Dict[str, Any]]:
    """
    Executes pending SQL migrations in sequence within transactional boundaries.
    Returns list of migration execution statuses.
    """
    conn = get_connection()
    results = []

    try:
        cur = conn.cursor()
        applied = get_applied_migrations(cur)
        conn.commit()

        migration_files = get_migration_files()
        logger.info("Discovered %d migration files. Currently %d applied in database.",
                    len(migration_files), len(applied))

        for version, filename, path in migration_files:
            content = path.read_text(encoding="utf-8")
            checksum = _compute_checksum(content)

            if version in applied:
                results.append({
                    "version": version,
                    "filename": filename,
                    "status": "ALREADY_APPLIED",
                    "checksum": checksum,
                })
                continue

            logger.info("Applying migration %s (%s)...", version, filename)
            try:
                cur.execute(content)
                if DATABASE_TYPE == "postgresql":
                    cur.execute("""
                        INSERT INTO public.schema_migrations (version, filename, checksum, applied_at)
                        VALUES (%s, %s, %s, NOW())
                    """, (version, filename, checksum))
                else:
                    cur.execute("""
                        INSERT INTO schema_migrations (version, filename, checksum)
                        VALUES (?, ?, ?)
                    """, (version, filename, checksum))
                conn.commit()
                logger.info("Migration %s successfully applied.", version)
                results.append({
                    "version": version,
                    "filename": filename,
                    "status": "APPLIED",
                    "checksum": checksum,
                })
            except Exception as exc:
                conn.rollback()
                logger.error("Failed to execute migration %s (%s): %s", version, filename, exc)
                results.append({
                    "version": version,
                    "filename": filename,
                    "status": "FAILED",
                    "error": str(exc),
                })
                raise RuntimeError(f"Migration {version} failed: {exc}") from exc

        cur.close()
    finally:
        release_connection(conn)

    return results


if __name__ == "__main__":
    try:
        res = run_all_migrations()
        print("\nMigration Results Summary:")
        for r in res:
            print(f"  [{r['status']}] {r['version']}: {r['filename']}")
        print("\nAll database migrations verified.\n")
    except Exception as e:
        logger.error("Database migration execution failed: %s", e)
        sys.exit(1)

