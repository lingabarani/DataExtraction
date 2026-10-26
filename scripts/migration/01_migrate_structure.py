"""
DataExtraction — Phase 2, Step 1: Structured File Migration
============================================================
COPIES (never moves) files from OneExtraction and gmaps-scraper into the
DataExtraction monorepo layout.

Usage:
    python scripts/migration/01_migrate_structure.py
    python scripts/migration/01_migrate_structure.py --dry-run   # Preview only

Rules:
  - Source files are NEVER modified or deleted.
  - Existing destination files are NOT overwritten (use --force to override).
  - A migration report is written to scripts/migration/migration_report.json.
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# ── Path Roots ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
ONE_EX = Path("D:/Data Scraping Project POC/OneExtraction")
BOTA = ONE_EX / "botasaurus"
GMAPS = ONE_EX / "gmaps-scraper" / "gmaps-scraper"
PACKAGES = REPO_ROOT / "packages"
TESTS = REPO_ROOT / "tests"

# ── Migration Map: (source_path, destination_path, description) ───────────────
MIGRATION_MAP = [
    # ── Federal Scrapers (6 files — UNTOUCHED) ───────────────────────────────
    (BOTA / "fetch_cms_npi.py",     PACKAGES / "scrapers/federal/fetch_cms_npi.py",     "CMS NPI federal scraper"),
    (BOTA / "fetch_sec_edgar.py",   PACKAGES / "scrapers/federal/fetch_sec_edgar.py",   "SEC EDGAR federal scraper"),
    (BOTA / "fetch_fdic.py",        PACKAGES / "scrapers/federal/fetch_fdic.py",        "FDIC federal scraper"),
    (BOTA / "fetch_usaspending.py", PACKAGES / "scrapers/federal/fetch_usaspending.py", "USASpending federal scraper"),
    (BOTA / "fetch_propublica.py",  PACKAGES / "scrapers/federal/fetch_propublica.py",  "ProPublica federal scraper"),
    (BOTA / "fetch_sam_gov.py",     PACKAGES / "scrapers/federal/fetch_sam_gov.py",     "SAM.gov federal scraper"),

    # ── Pipeline Modules (6 files — UNTOUCHED) ───────────────────────────────
    (BOTA / "normalizer.py",        PACKAGES / "pipeline/normalizer.py",        "Data normalizer"),
    (BOTA / "deduplicator.py",      PACKAGES / "pipeline/deduplicator.py",      "Record deduplicator"),
    (BOTA / "lead_builder.py",      PACKAGES / "pipeline/lead_builder.py",      "Lead builder"),
    (BOTA / "contact_validator.py", PACKAGES / "pipeline/contact_validator.py", "Contact validator"),
    (BOTA / "tax_validator.py",     PACKAGES / "pipeline/tax_validator.py",     "Tax ID validator"),
    (BOTA / "geo_validator.py",     PACKAGES / "pipeline/geo_validator.py",     "Geographic validator"),

    # ── Infrastructure (10 files — UNTOUCHED) ─────────────────────────────────
    (BOTA / "db_connector.py",      PACKAGES / "infrastructure/db_connector.py",      "PostgreSQL connection pool"),
    (BOTA / "config_manager.py",    PACKAGES / "infrastructure/config_manager.py",    "Configuration manager + AWS Secrets"),
    (BOTA / "structured_logger.py", PACKAGES / "infrastructure/structured_logger.py", "Structured JSON logger"),
    (BOTA / "metrics.py",           PACKAGES / "infrastructure/metrics.py",           "Prometheus metrics"),
    (BOTA / "dead_letter_queue.py", PACKAGES / "infrastructure/dead_letter_queue.py", "Dead letter queue"),
    (BOTA / "http_client.py",       PACKAGES / "infrastructure/http_client.py",       "HTTP client"),
    (BOTA / "db_config.py",         PACKAGES / "infrastructure/db_config.py",         "DB config adapter"),
    (BOTA / "setup_postgres.py",    PACKAGES / "infrastructure/setup_postgres.py",    "PostgreSQL setup"),
    (BOTA / "migrate_schema.py",    PACKAGES / "infrastructure/migrate_schema.py",    "Database schema migration"),
    (BOTA / "init_db.sql",          PACKAGES / "infrastructure/init_db.sql",          "Initial DB DDL schema"),

    # ── Ops & DB Scripts ─────────────────────────────────────────────────────
    (ONE_EX / "scripts/db/backup_postgres.py",  REPO_ROOT / "scripts/db/backup_postgres.py",   "DB backup script"),
    (ONE_EX / "scripts/db/restore_postgres.py", REPO_ROOT / "scripts/db/restore_postgres.py",  "DB restore script"),
    (ONE_EX / "scripts/ops/archive_cleanup.py", REPO_ROOT / "scripts/ops/archive_cleanup.py",  "Archive cleanup script"),

    # ── OpenMap Engine (7 files — UNTOUCHED) ─────────────────────────────────
    (BOTA / "openmap_engine/__init__.py",      PACKAGES / "scrapers/open_map/__init__.py",      "OpenMap engine init"),
    (BOTA / "openmap_engine/checkpoint.py",    PACKAGES / "scrapers/open_map/checkpoint.py",    "OSM checkpoint"),
    (BOTA / "openmap_engine/circuit_breaker.py", PACKAGES / "scrapers/open_map/circuit_breaker.py", "OSM circuit breaker"),
    (BOTA / "openmap_engine/config.py",        PACKAGES / "scrapers/open_map/config.py",        "OSM config"),
    (BOTA / "openmap_engine/connector.py",     PACKAGES / "scrapers/open_map/connector.py",     "OSM connector"),
    (BOTA / "openmap_engine/quadtree.py",      PACKAGES / "scrapers/open_map/quadtree.py",      "OSM quadtree"),
    (BOTA / "openmap_engine/taxonomy.py",      PACKAGES / "scrapers/open_map/taxonomy.py",      "OSM taxonomy"),

    # ── API Layer (11 files — UNTOUCHED) ──────────────────────────────────────
    (BOTA / "api_server.py",                PACKAGES / "api/api_server.py",                      "FastAPI application"),
    (BOTA / "api/__init__.py",              PACKAGES / "api/routers/__init__.py",                 "API routers init"),
    (BOTA / "api/auth_router.py",           PACKAGES / "api/routers/auth_router.py",              "Auth router"),
    (BOTA / "api/leads_router.py",          PACKAGES / "api/routers/leads_router.py",             "Leads router"),
    (BOTA / "api/stats_router.py",          PACKAGES / "api/routers/stats_router.py",             "Stats router"),
    (BOTA / "api/export_router.py",         PACKAGES / "api/routers/export_router.py",            "Export router"),
    (BOTA / "api/duplicates_router.py",     PACKAGES / "api/routers/duplicates_router.py",        "Duplicates router"),
    (BOTA / "api/scraper_router.py",        PACKAGES / "api/routers/scraper_router.py",           "Scraper router"),
    (BOTA / "api/ai_router.py",             PACKAGES / "api/routers/ai_router.py",                "AI router"),
    (BOTA / "api/map_extraction_router.py", PACKAGES / "api/routers/map_extraction_router.py",    "Map extraction router"),
    (BOTA / "api/dlq_router.py",            PACKAGES / "api/routers/dlq_router.py",               "DLQ router"),
    (BOTA / "api/deps.py",                  PACKAGES / "api/routers/deps.py",                     "API deps"),

    # ── Backend Tests (6 files — UNTOUCHED) ──────────────────────────────────
    (BOTA / "tests/conftest.py",                      TESTS / "unit/backend/conftest.py",                     "Backend conftest"),
    (BOTA / "tests/test_phase1_security_config.py",   TESTS / "unit/backend/test_phase1_security_config.py",  "Security config tests"),
    (BOTA / "tests/test_phase2_validation.py",        TESTS / "unit/backend/test_phase2_validation.py",       "Validation tests"),
    (BOTA / "tests/test_phase3_ingestion_dedup.py",   TESTS / "unit/backend/test_phase3_ingestion_dedup.py",  "Ingestion/dedup tests"),
    (BOTA / "tests/test_phase4_db_integrity.py",      TESTS / "unit/backend/test_phase4_db_integrity.py",     "DB integrity tests"),
    (BOTA / "tests/test_phase5_orchestration_dlq.py", TESTS / "unit/backend/test_phase5_orchestration_dlq.py","Orchestration/DLQ tests"),
    (BOTA / "tests/test_phase6_delivery.py",          TESTS / "unit/backend/test_phase6_delivery.py",         "Delivery tests"),
]

# gmaps-scraper: entire src tree copied as a block
GMAPS_SRC_MAP = [
    # Core source files
    (GMAPS / "src/gmaps_scraper/__init__.py",      PACKAGES / "scrapers/google_maps/src/gmaps_scraper/__init__.py"),
    (GMAPS / "src/gmaps_scraper/__main__.py",      PACKAGES / "scrapers/google_maps/src/gmaps_scraper/__main__.py"),
    (GMAPS / "src/gmaps_scraper/checkpoint.py",    PACKAGES / "scrapers/google_maps/src/gmaps_scraper/checkpoint.py"),
    (GMAPS / "src/gmaps_scraper/cli.py",           PACKAGES / "scrapers/google_maps/src/gmaps_scraper/cli.py"),
    (GMAPS / "src/gmaps_scraper/config.py",        PACKAGES / "scrapers/google_maps/src/gmaps_scraper/config.py"),
    (GMAPS / "src/gmaps_scraper/db.py",            PACKAGES / "scrapers/google_maps/src/gmaps_scraper/db.py"),
    (GMAPS / "src/gmaps_scraper/details.py",       PACKAGES / "scrapers/google_maps/src/gmaps_scraper/details.py"),
    (GMAPS / "src/gmaps_scraper/export.py",        PACKAGES / "scrapers/google_maps/src/gmaps_scraper/export.py"),
    (GMAPS / "src/gmaps_scraper/fallback_browser.py", PACKAGES / "scrapers/google_maps/src/gmaps_scraper/fallback_browser.py"),
    (GMAPS / "src/gmaps_scraper/http.py",          PACKAGES / "scrapers/google_maps/src/gmaps_scraper/http.py"),
    (GMAPS / "src/gmaps_scraper/jobs.py",          PACKAGES / "scrapers/google_maps/src/gmaps_scraper/jobs.py"),
    (GMAPS / "src/gmaps_scraper/logging_setup.py", PACKAGES / "scrapers/google_maps/src/gmaps_scraper/logging_setup.py"),
    (GMAPS / "src/gmaps_scraper/models.py",        PACKAGES / "scrapers/google_maps/src/gmaps_scraper/models.py"),
    (GMAPS / "src/gmaps_scraper/orchestrator.py",  PACKAGES / "scrapers/google_maps/src/gmaps_scraper/orchestrator.py"),
    (GMAPS / "src/gmaps_scraper/parser_state.py",  PACKAGES / "scrapers/google_maps/src/gmaps_scraper/parser_state.py"),
    (GMAPS / "src/gmaps_scraper/photos.py",        PACKAGES / "scrapers/google_maps/src/gmaps_scraper/photos.py"),
    (GMAPS / "src/gmaps_scraper/reviews.py",       PACKAGES / "scrapers/google_maps/src/gmaps_scraper/reviews.py"),
    (GMAPS / "src/gmaps_scraper/scope.py",         PACKAGES / "scrapers/google_maps/src/gmaps_scraper/scope.py"),
    (GMAPS / "src/gmaps_scraper/search.py",        PACKAGES / "scrapers/google_maps/src/gmaps_scraper/search.py"),
    (GMAPS / "src/gmaps_scraper/taxonomy.py",      PACKAGES / "scrapers/google_maps/src/gmaps_scraper/taxonomy.py"),
    (GMAPS / "src/gmaps_scraper/tiling.py",        PACKAGES / "scrapers/google_maps/src/gmaps_scraper/tiling.py"),
    # pyproject.toml
    (GMAPS / "pyproject.toml",                     PACKAGES / "scrapers/google_maps/pyproject.toml"),
]


def migrate(dry_run: bool = False, force: bool = False) -> dict:
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "copied": [],
        "skipped": [],
        "missing_source": [],
        "errors": [],
    }

    all_entries = MIGRATION_MAP + [(s, d, "gmaps-scraper") for s, d in GMAPS_SRC_MAP]

    for entry in all_entries:
        if len(entry) == 3:
            src, dst, desc = entry
        else:
            src, dst = entry
            desc = "gmaps-scraper"

        if not src.exists():
            report["missing_source"].append({"src": str(src), "desc": desc})
            print(f"  ⚠  MISSING: {src.name} ({desc})")
            continue

        if dst.exists() and not force:
            report["skipped"].append({"src": str(src), "dst": str(dst)})
            print(f"  ⏭  SKIP (exists): {dst.relative_to(REPO_ROOT)}")
            continue

        if not dry_run:
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                report["copied"].append({"src": str(src), "dst": str(dst), "desc": desc})
                print(f"  ✅ COPIED: {src.name} → {dst.relative_to(REPO_ROOT)}")
            except Exception as exc:
                report["errors"].append({"src": str(src), "error": str(exc)})
                print(f"  ❌ ERROR: {src.name} — {exc}")
        else:
            report["copied"].append({"src": str(src), "dst": str(dst), "desc": desc, "dry_run": True})
            print(f"  [DRY] WOULD COPY: {src.name} → {dst.relative_to(REPO_ROOT)}")

    # Copy gmaps tests directory tree
    gmaps_tests_src = GMAPS / "tests"
    gmaps_tests_dst = TESTS / "unit/gmaps"
    if gmaps_tests_src.exists():
        for test_file in gmaps_tests_src.rglob("*.py"):
            rel = test_file.relative_to(gmaps_tests_src)
            dst = gmaps_tests_dst / rel
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if not dst.exists() or force:
                    shutil.copy2(test_file, dst)
                    print(f"  ✅ COPIED test: {test_file.name} → tests/unit/gmaps/{rel}")
            else:
                print(f"  [DRY] WOULD COPY test: {test_file.name} → tests/unit/gmaps/{rel}")

    # Copy gmaps full src tree (including geo, incremental, storage, web, website)
    gmaps_src_root = GMAPS / "src" / "gmaps_scraper"
    gmaps_dst_root = PACKAGES / "scrapers" / "google_maps" / "src" / "gmaps_scraper"
    if gmaps_src_root.exists():
        for f in gmaps_src_root.rglob("*"):
            if f.is_file() and "__pycache__" not in f.parts and not f.name.endswith(".pyc"):
                rel = f.relative_to(gmaps_src_root)
                dst = gmaps_dst_root / rel
                if not dry_run:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if not dst.exists() or force:
                        shutil.copy2(f, dst)
                        print(f"  ✅ COPIED gmaps module: {rel}")
                else:
                    print(f"  [DRY] WOULD COPY gmaps module: {rel}")

    # Copy gmaps config directory
    gmaps_cfg_src = GMAPS / "config"
    gmaps_cfg_dst = PACKAGES / "scrapers" / "google_maps" / "config"
    if gmaps_cfg_src.exists():
        for f in gmaps_cfg_src.rglob("*"):
            if f.is_file():
                rel = f.relative_to(gmaps_cfg_src)
                dst = gmaps_cfg_dst / rel
                if not dry_run:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if not dst.exists() or force:
                        shutil.copy2(f, dst)
                        print(f"  ✅ COPIED gmaps config: {rel}")
                else:
                    print(f"  [DRY] WOULD COPY gmaps config: {rel}")

    # Copy gmaps requirements.txt if present
    gmaps_req = GMAPS / "requirements.txt"
    if gmaps_req.exists():
        dst = PACKAGES / "scrapers" / "google_maps" / "requirements.txt"
        if not dry_run:
            shutil.copy2(gmaps_req, dst)
        print(f"  ✅ COPIED: gmaps requirements.txt")

    # Copy frontend (Next.js 15) excluding node_modules, .next, etc.
    frontend_src = ONE_EX / "frontend"
    frontend_dst = PACKAGES / "frontend"
    if frontend_src.exists():
        exclude_dirs = {".next", "node_modules", ".git", ".turbo"}
        for f in frontend_src.rglob("*"):
            if any(part in exclude_dirs for part in f.parts):
                continue
            if f.is_file() and not f.name.endswith(".tsbuildinfo"):
                rel = f.relative_to(frontend_src)
                dst = frontend_dst / rel
                if not dry_run:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if not dst.exists() or force:
                        shutil.copy2(f, dst)
                else:
                    pass
        print(f"  ✅ COPIED frontend Next.js 15 application tree (clean)")

    # Save report
    report_path = Path(__file__).parent / "migration_report.json"
    report_path.write_text(json.dumps(report, indent=2))

    print(f"\n{'='*60}")
    print(f"Migration Report:")
    print(f"  Copied:         {len(report['copied'])}")
    print(f"  Skipped:        {len(report['skipped'])}")
    print(f"  Missing source: {len(report['missing_source'])}")
    print(f"  Errors:         {len(report['errors'])}")
    print(f"  Report saved:   {report_path}")

    if report["missing_source"]:
        print(f"\n⚠  WARNING: {len(report['missing_source'])} source files not found:")
        for m in report["missing_source"]:
            print(f"     {m['src']}")

    if report["errors"]:
        print(f"\n❌ ERRORS — review migration_report.json")
        sys.exit(1)

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DataExtraction file migration")
    parser.add_argument("--dry-run", action="store_true", help="Preview without copying")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"DataExtraction — Phase 2 File Migration")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'EXECUTE'}")
    print(f"{'='*60}\n")

    migrate(dry_run=args.dry_run, force=args.force)
