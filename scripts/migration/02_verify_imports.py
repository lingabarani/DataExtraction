"""
DataExtraction — Phase 2, Step 2: Import Verification & Path Repair
====================================================================
Scans all migrated Python files in packages/ and reports any import
statements that reference the old OneExtraction path layout.

IMPORTANT: This script REPORTS problems — it does NOT auto-rewrite
scraper files. Scrapers are NEVER modified.

Import repair is handled via sys.path injection in activity wrappers
(packages/temporal/activities/*.py), not by touching the scrapers.

Usage:
    python scripts/migration/02_verify_imports.py
    python scripts/migration/02_verify_imports.py --verbose
"""

import ast
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGES = REPO_ROOT / "packages"

# Imports that are expected to resolve from within each package boundary
# These will be flagged if found in the WRONG package's files
CROSS_BOUNDARY_IMPORTS = {
    # Old OneExtraction flat-layout imports (now live under packages/infrastructure)
    "from config_manager import",
    "from db_connector import",
    "from structured_logger import",
    "from metrics import",
    "from dead_letter_queue import",
    "from http_client import",
    "import config_manager",
    "import db_connector",
    "import structured_logger",
    "import dead_letter_queue",
}

# Files exempt from import checks (these are scrapers — they use flat imports by design)
# Activity wrappers bridge the import gap via sys.path; scrapers stay untouched.
EXEMPT_PATHS = {
    "packages/scrapers/federal",
    "packages/scrapers/google_maps",
    "packages/scrapers/open_map",
    "packages/pipeline",
}


def is_exempt(filepath: Path) -> bool:
    rel = str(filepath.relative_to(REPO_ROOT)).replace("\\", "/")
    return any(rel.startswith(exempt) for exempt in EXEMPT_PATHS)


def check_imports(filepath: Path) -> list[dict]:
    """Returns list of import issues found in the file."""
    issues = []
    try:
        source = filepath.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(source.splitlines(), start=1):
            line_stripped = line.strip()
            for pattern in CROSS_BOUNDARY_IMPORTS:
                if line_stripped.startswith(pattern):
                    issues.append({
                        "file": str(filepath.relative_to(REPO_ROOT)),
                        "line": lineno,
                        "content": line_stripped,
                        "pattern": pattern,
                        "fix": "sys.path injection in activity wrapper (do NOT modify this file)",
                    })
    except Exception as exc:
        issues.append({
            "file": str(filepath.relative_to(REPO_ROOT)),
            "line": 0,
            "content": f"ERROR reading file: {exc}",
            "pattern": "N/A",
            "fix": "N/A",
        })
    return issues


def verify_syntax(filepath: Path) -> dict | None:
    """Returns syntax error info if file has a parse error."""
    try:
        source = filepath.read_text(encoding="utf-8", errors="ignore")
        ast.parse(source)
        return None
    except SyntaxError as exc:
        return {
            "file": str(filepath.relative_to(REPO_ROOT)),
            "line": exc.lineno,
            "error": str(exc.msg),
        }


def main(verbose: bool = False):
    all_issues = []
    syntax_errors = []
    files_checked = 0
    exempt_count = 0

    print(f"\n{'='*60}")
    print("DataExtraction — Phase 2 Import Verification")
    print(f"{'='*60}")

    for py_file in PACKAGES.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue

        files_checked += 1

        # Syntax check — every file must be parseable
        err = verify_syntax(py_file)
        if err:
            syntax_errors.append(err)
            print(f"  ❌ SYNTAX ERROR: {err['file']}:{err['line']} — {err['error']}")
            continue

        if is_exempt(py_file):
            exempt_count += 1
            if verbose:
                print(f"  ⏭  EXEMPT: {py_file.relative_to(REPO_ROOT)}")
            continue

        issues = check_imports(py_file)
        if issues:
            all_issues.extend(issues)
            for issue in issues:
                print(f"  ⚠  CROSS-BOUNDARY IMPORT: {issue['file']}:{issue['line']}")
                print(f"     {issue['content']}")
                print(f"     FIX: {issue['fix']}")

    # Summary
    print(f"\n{'='*60}")
    print(f"Results:")
    print(f"  Files checked:   {files_checked}")
    print(f"  Files exempt:    {exempt_count} (scrapers — sys.path handled in activities)")
    print(f"  Syntax errors:   {len(syntax_errors)}")
    print(f"  Import issues:   {len(all_issues)}")

    report = {
        "files_checked": files_checked,
        "exempt_files": exempt_count,
        "syntax_errors": syntax_errors,
        "import_issues": all_issues,
    }
    report_path = Path(__file__).parent / "import_report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"  Report saved:    {report_path}")

    if syntax_errors:
        print("\n❌ FAIL: Syntax errors must be resolved before proceeding to Phase 3")
        sys.exit(1)

    if all_issues:
        print(f"\n⚠  WARNING: {len(all_issues)} cross-boundary imports found.")
        print("   These are in non-scraper packages and require manual review.")
        print("   Scraper imports (exempt) are handled via sys.path in activity wrappers.")

    print("\n✅ Import verification complete.")


if __name__ == "__main__":
    verbose = "--verbose" in sys.argv
    main(verbose=verbose)
