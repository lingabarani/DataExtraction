#!/usr/bin/env python3
"""
OneExtraction — Enterprise Codebase Cleanup & Archival Automation
Safely archives unused, obsolete, temporary, redundant, and legacy files
into a structured, git-ignored `archived/` directory with full manifest tracking.
"""

import argparse
import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

_ROOT_DIR = Path(__file__).resolve().parent.parent.parent
_ARCHIVE_DIR = _ROOT_DIR / "archived"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [CLEANUP] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("oneextraction.cleanup")

# Target categories and files for safe archival
CLEANUP_TARGETS: List[Dict[str, str]] = [
    # ── Category 1: Runtime Logs & Duplicate Root Configs ────────────────────
    {"source": "backend.log", "dest_sub": "logs", "reason": "Ephemeral runtime backend log file"},
    {"source": "frontend.log", "dest_sub": "logs", "reason": "Ephemeral runtime frontend log file"},
    {"source": ".gitignore-production", "dest_sub": "legacy_configs", "reason": "Duplicate of production .gitignore"},
    
    # ── Category 2: Root Word Doc Generators & Standalone Helpers ────────────
    {"source": "generate_executive_doc.py", "dest_sub": "presentation_tools", "reason": "One-off Word document generator script"},
    {"source": "generate_comprehensive_guide_doc.py", "dest_sub": "presentation_tools", "reason": "One-off Word document generator script"},
    {"source": "debug_api.py", "dest_sub": "legacy_scripts", "reason": "Ad-hoc API debugging script superseded by manage.ps1"},
    {"source": "test_stats.py", "dest_sub": "legacy_scripts", "reason": "Ad-hoc stats test script superseded by unit test suite"},
    {"source": "run_pdl.py", "dest_sub": "legacy_scripts", "reason": "Root wrapper script superseded by pipeline orchestrator"},
    {"source": "setup.py", "dest_sub": "legacy_configs", "reason": "Broken package setup file referencing non-existent root src/"},
    {"source": "IMPLEMENTATION_PLAN.md", "dest_sub": "docs", "reason": "Root duplicate of docs/IMPLEMENTATION_PLAN.md"},
    {"source": ".kiro", "dest_sub": "editor", "reason": "Legacy IDE editor workspace metadata"},

    # ── Category 3: Export Tabular Dumps (CSV) ───────────────────────────────
    {"source": "exports", "dest_sub": "exports", "reason": "Generated tabular data exports (~7.6 MB) committed to git"},

    # ── Category 4: Open Map Extraction Engine Ephemera ──────────────────────
    {"source": "Open Map Extraction Engine/.kilo", "dest_sub": "editor", "reason": "Legacy IDE editor metadata in OpenMap engine"},

    # ── Category 5: Botasaurus Broken Legacy Tests ───────────────────────────
    {"source": "botasaurus/tests/test_bulk_converter.py", "dest_sub": "legacy_tests", "reason": "Legacy test importing uninstalled pandas"},
    {"source": "botasaurus/tests/test_connectors.py", "dest_sub": "legacy_tests", "reason": "Legacy test importing uninstalled pytest"},
    {"source": "botasaurus/tests/test_deduplication.py", "dest_sub": "legacy_tests", "reason": "Legacy test importing uninstalled pytest"},
    {"source": "botasaurus/tests/test_email_verifier.py", "dest_sub": "legacy_tests", "reason": "Legacy test importing uninstalled pytest"},
    {"source": "botasaurus/tests/test_entity_resolution.py", "dest_sub": "legacy_tests", "reason": "Legacy test importing uninstalled pytest"},
    {"source": "botasaurus/tests/test_forge_merges.py", "dest_sub": "legacy_tests", "reason": "Legacy test importing uninstalled pandas"},
    {"source": "botasaurus/tests/test_normalization.py", "dest_sub": "legacy_tests", "reason": "Legacy test importing uninstalled pytest"},
    {"source": "botasaurus/tests/test_separated_pipelines.py", "dest_sub": "legacy_tests", "reason": "Legacy test importing uninstalled pytest"},
    {"source": "botasaurus/tests/test_validation.py", "dest_sub": "legacy_tests", "reason": "Legacy test importing uninstalled pytest"},
    {"source": "botasaurus/tests/test_mcp_rdap.py", "dest_sub": "legacy_tests", "reason": "Legacy isolated test superseded by Phase 1-6 suites"},
    {"source": "botasaurus/tests/test_opendirectories_client.py", "dest_sub": "legacy_tests", "reason": "Legacy isolated test superseded by Phase 1-6 suites"},
    {"source": "botasaurus/tests/test_person_enrichment.py", "dest_sub": "legacy_tests", "reason": "Legacy isolated test superseded by Phase 1-6 suites"},
    {"source": "botasaurus/tests/test_pipeline.py", "dest_sub": "legacy_tests", "reason": "Legacy isolated test superseded by Phase 1-6 suites"},
    {"source": "botasaurus/tests/test_api_integration.py", "dest_sub": "legacy_tests", "reason": "Legacy isolated test superseded by Phase 6 delivery suite"},

    # ── Category 6: Botasaurus Ad-Hoc Scripts & Standalone Tools ─────────────
    {"source": "botasaurus/test_all_keys.py", "dest_sub": "legacy_scripts", "reason": "Ad-hoc key validation script"},
    {"source": "botasaurus/test_dupes.py", "dest_sub": "legacy_scripts", "reason": "Ad-hoc deduplication test script"},
    {"source": "botasaurus/test_ingestion_debug.py", "dest_sub": "legacy_scripts", "reason": "Ad-hoc debug script"},
    {"source": "botasaurus/test_mcp_server.py", "dest_sub": "legacy_scripts", "reason": "Ad-hoc MCP server tester"},
    {"source": "botasaurus/test_sam_key.py", "dest_sub": "legacy_scripts", "reason": "Ad-hoc SAM key tester"},
    {"source": "botasaurus/test_stats_direct.py", "dest_sub": "legacy_scripts", "reason": "Ad-hoc direct stats test script"},
    {"source": "botasaurus/bot_detection_tests.py", "dest_sub": "legacy_scripts", "reason": "Experimental bot detection script"},
    {"source": "botasaurus/production_test.py", "dest_sub": "legacy_scripts", "reason": "Manual production test script superseded by CI"},
    {"source": "botasaurus/analyse_schema.py", "dest_sub": "legacy_scripts", "reason": "One-off schema inspection script"},
    {"source": "botasaurus/build_stats_cache.py", "dest_sub": "legacy_scripts", "reason": "Ad-hoc stats cache builder"},
    {"source": "botasaurus/check_coverage.py", "dest_sub": "legacy_scripts", "reason": "Ad-hoc coverage check script"},
    {"source": "botasaurus/check_progress.py", "dest_sub": "legacy_scripts", "reason": "Ad-hoc progress checker"},
    {"source": "botasaurus/check_sources_now.py", "dest_sub": "legacy_scripts", "reason": "Ad-hoc source availability checker"},
    {"source": "botasaurus/check_stats.py", "dest_sub": "legacy_scripts", "reason": "Ad-hoc stats check script"},
    {"source": "botasaurus/compare_data_quality.py", "dest_sub": "legacy_scripts", "reason": "Ad-hoc quality comparison script"},
    {"source": "botasaurus/create_dedup_indexes.py", "dest_sub": "legacy_scripts", "reason": "Superseded by migrate_schema.py"},
    {"source": "botasaurus/create_perf_indexes.py", "dest_sub": "legacy_scripts", "reason": "Superseded by migrate_schema.py"},
    {"source": "botasaurus/create_lead_tables.py", "dest_sub": "legacy_scripts", "reason": "Superseded by setup_postgres.py"},
    {"source": "botasaurus/migrate_to_leads.py", "dest_sub": "legacy_scripts", "reason": "Superseded by migrate_schema.py"},
    {"source": "botasaurus/email_stats_dashboard.py", "dest_sub": "legacy_scripts", "reason": "Standalone CLI email dashboard"},
    {"source": "botasaurus/export_verified_emails.py", "dest_sub": "legacy_scripts", "reason": "Superseded by export_router.py"},
    {"source": "botasaurus/final_verify.py", "dest_sub": "legacy_scripts", "reason": "Ad-hoc manual verification script"},
    {"source": "botasaurus/find_duplicates.py", "dest_sub": "legacy_scripts", "reason": "Superseded by duplicates_router.py"},
    {"source": "botasaurus/fix_fk.py", "dest_sub": "legacy_scripts", "reason": "One-off foreign key patch script"},
    {"source": "botasaurus/fix_warnings.py", "dest_sub": "legacy_scripts", "reason": "One-off warning fix script"},
    {"source": "botasaurus/get_real_sam_emails.py", "dest_sub": "legacy_scripts", "reason": "Ad-hoc SAM scraper snippet"},
    {"source": "botasaurus/inspect_data_fields.py", "dest_sub": "legacy_scripts", "reason": "Ad-hoc field inspector"},
    {"source": "botasaurus/inspect_schema.py", "dest_sub": "legacy_scripts", "reason": "Ad-hoc schema inspector"},
    {"source": "botasaurus/quick_count.py", "dest_sub": "legacy_scripts", "reason": "Ad-hoc record counter"},
    {"source": "botasaurus/verify_api.py", "dest_sub": "legacy_scripts", "reason": "Manual API verifier"},
    {"source": "botasaurus/verify_final.py", "dest_sub": "legacy_scripts", "reason": "Manual final verifier"},
    {"source": "botasaurus/verify_leads.py", "dest_sub": "legacy_scripts", "reason": "Manual leads verifier"},
    {"source": "botasaurus/verify_postgres.py", "dest_sub": "legacy_scripts", "reason": "Manual postgres verifier"},
    {"source": "botasaurus/verify_real_data.py", "dest_sub": "legacy_scripts", "reason": "Manual real data verifier"},
    {"source": "botasaurus/wait_for_stats.py", "dest_sub": "legacy_scripts", "reason": "Polling script superseded by metrics.py"},
    {"source": "botasaurus/reset_pg_password.ps1", "dest_sub": "legacy_scripts", "reason": "One-off local password reset script"},
    {"source": "botasaurus/docker-compose.yml", "dest_sub": "legacy_configs", "reason": "Superseded by root docker-compose.yml"},

    # ── Category 7: Botasaurus Standalone Ingestion Wrappers (Superseded) ─────
    {"source": "botasaurus/extract_contacts.py", "dest_sub": "legacy_scripts", "reason": "Standalone contact extractor script"},
    {"source": "botasaurus/extract_csuite_contacts.py", "dest_sub": "legacy_scripts", "reason": "Standalone c-suite extractor script"},
    {"source": "botasaurus/extract_real_emails.py", "dest_sub": "legacy_scripts", "reason": "Standalone email extractor script"},
    {"source": "botasaurus/ingest_all_contacts.sh", "dest_sub": "legacy_scripts", "reason": "Bash ingestion script superseded by manage.ps1"},
    {"source": "botasaurus/ingest_data.py", "dest_sub": "legacy_scripts", "reason": "Standalone ingestion script superseded by orchestrator"},
    {"source": "botasaurus/ingest_leads.py", "dest_sub": "legacy_scripts", "reason": "Standalone lead ingestion script superseded by orchestrator"},
    {"source": "botasaurus/main_us.py", "dest_sub": "legacy_scripts", "reason": "Legacy CLI entry point superseded by orchestrator"},
    {"source": "botasaurus/run_all_sources.py", "dest_sub": "legacy_scripts", "reason": "Superseded by pipeline_orchestrator.py"},
    {"source": "botasaurus/run_full_contact_extraction.py", "dest_sub": "legacy_scripts", "reason": "Superseded by orchestrator"},
    {"source": "botasaurus/run_pdl.py", "dest_sub": "legacy_scripts", "reason": "Superseded by orchestrator"},

    # ── Category 8: Botasaurus Legacy Docs & Notes ───────────────────────────
    {"source": "botasaurus/API_KEY_TEST_COMMANDS.md", "dest_sub": "docs", "reason": "Superseded by docs/operations/"},
    {"source": "botasaurus/CLAUDE_DESKTOP_CONFIG.md", "dest_sub": "docs", "reason": "Legacy MCP desktop configuration guide"},
    {"source": "botasaurus/claude_desktop_config.json", "dest_sub": "docs", "reason": "Legacy MCP desktop configuration JSON"},
    {"source": "botasaurus/MCP_INTEGRATION_GUIDE.md", "dest_sub": "docs", "reason": "Superseded by docs/architecture/"},
    {"source": "botasaurus/QUICK_START_MCP.md", "dest_sub": "docs", "reason": "Superseded by docs/"},
    {"source": "botasaurus/REAL_DATA_PIPELINE.md", "dest_sub": "docs", "reason": "Superseded by docs/architecture/"},
    {"source": "botasaurus/run-postgres-cloud-sql-instance.md", "dest_sub": "docs", "reason": "Superseded by docs/deployment/"},
    {"source": "botasaurus/run-scraper-in-kubernetes.md", "dest_sub": "docs", "reason": "Superseded by deploy/k8s/ & docs/deployment/"},
    {"source": "botasaurus/run-supabase-postgres-instance.md", "dest_sub": "docs", "reason": "Superseded by docs/deployment/"},

    # ── Category 9: Botasaurus Presentation & Dataforge Scripts ──────────────
    {"source": "botasaurus/scripts/generate_all_ceo_slides.py", "dest_sub": "presentation_tools", "reason": "Ad-hoc slide generation script"},
    {"source": "botasaurus/scripts/capture_ceo_sections.py", "dest_sub": "presentation_tools", "reason": "Ad-hoc slide screenshot script"},
    {"source": "botasaurus/scripts/capture_presentation_screenshots.py", "dest_sub": "presentation_tools", "reason": "Ad-hoc presentation screenshot script"},
    {"source": "botasaurus/scripts/setup_dataforge.ps1", "dest_sub": "legacy_scripts", "reason": "Legacy Dataforge setup script"},
    {"source": "botasaurus/scripts/setup_dataforge.sh", "dest_sub": "legacy_scripts", "reason": "Legacy Dataforge setup script"},
    {"source": "botasaurus/scripts/dataforge_loader.py", "dest_sub": "legacy_scripts", "reason": "Legacy Dataforge loader script"},
    {"source": "botasaurus/scripts/dataforge_integration_guide.md", "dest_sub": "docs", "reason": "Legacy Dataforge integration documentation"},
    {"source": "botasaurus/scripts/verify_week1_setup.py", "dest_sub": "legacy_scripts", "reason": "Legacy Week 1 verification script"},
]


def run_cleanup(dry_run: bool = False) -> Tuple[int, int]:
    """
    Executes or simulates migration of files into `archived/`.
    Returns (migrated_count, skipped_count).
    """
    manifest_entries = []
    migrated = 0
    skipped = 0

    mode_label = "[DRY RUN]" if dry_run else "[EXECUTE]"
    logger.info("%s Initiating OneExtraction Project Cleanup & Archival...", mode_label)

    for item in CLEANUP_TARGETS:
        rel_src = item["source"]
        sub_dir = item["dest_sub"]
        reason = item["reason"]

        src_path = _ROOT_DIR / rel_src
        dest_dir = _ARCHIVE_DIR / sub_dir
        dest_path = dest_dir / src_path.name

        if not src_path.exists():
            skipped += 1
            continue

        if dry_run:
            logger.info("[DRY RUN] Would move: %s -> %s (Reason: %s)", rel_src, dest_path.relative_to(_ROOT_DIR), reason)
            migrated += 1
            continue

        # Execute move
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            if src_path.is_dir():
                # If destination dir already exists, merge/replace
                if dest_path.exists():
                    shutil.rmtree(dest_path)
                shutil.move(str(src_path), str(dest_path))
            else:
                shutil.move(str(src_path), str(dest_path))

            logger.info("Archived: %s -> %s", rel_src, dest_path.relative_to(_ROOT_DIR))
            migrated += 1
            manifest_entries.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "original_path": rel_src,
                "archived_path": str(dest_path.relative_to(_ROOT_DIR)),
                "reason": reason,
            })
        except Exception as e:
            logger.error("Failed to archive %s: %s", rel_src, e)

    if not dry_run and manifest_entries:
        _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        manifest_file = _ARCHIVE_DIR / "ARCHIVE_MANIFEST.json"
        
        # Load existing manifest if present
        existing = []
        if manifest_file.exists():
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = []
                
        existing.extend(manifest_entries)
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
            
        logger.info("Saved archive catalog manifest: %s (%d total entries)", manifest_file, len(existing))

    logger.info("%s Summary: %d items archived, %d skipped.", mode_label, migrated, skipped)
    return migrated, skipped


def main():
    parser = argparse.ArgumentParser(description="OneExtraction Project Cleanup & Archival Automation")
    parser.add_argument("--dry-run", action="store_true", help="Simulate archival without moving files")
    parser.add_argument("--execute", action="store_true", help="Execute the archival moves")

    args = parser.parse_args()

    if not args.execute and not args.dry_run:
        logger.info("No flag provided; defaulting to --dry-run simulation.")
        run_cleanup(dry_run=True)
        logger.info("To perform actual moves, run with: python scripts/ops/archive_cleanup.py --execute")
        return

    run_cleanup(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
