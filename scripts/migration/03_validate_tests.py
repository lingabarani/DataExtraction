"""
DataExtraction — Comprehensive Test Validation Gate
===================================================
Runs all five test suites in the monorepo:
1. Backend Unit Tests (122 tests)
2. Google Maps Scraper Tests (168 tests)
3. OpenMap Spatial Engine Tests (31 tests)
4. Autonomous Agent Behavior Tests (12 tests)
5. End-to-End Pipeline & Saga Tests (16 tests)

Total: 349 tests. ALL must pass (100% green).

Usage:
    python scripts/migration/03_validate_tests.py
    python scripts/migration/03_validate_tests.py --suite backend
    python scripts/migration/03_validate_tests.py --suite gmaps
    python scripts/migration/03_validate_tests.py --suite osm
    python scripts/migration/03_validate_tests.py --suite agents
    python scripts/migration/03_validate_tests.py --suite e2e
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable

SUITES = {
    "backend": {
        "description": "OneExtraction backend tests (122 tests)",
        "cmd": [PYTHON, "-m", "unittest", "discover", "-s", "tests/unit/backend", "-p", "test_phase*.py"],
        "expected_count": 122,
        "env": {"ENVIRONMENT": "test"},
    },
    "gmaps": {
        "description": "Google Maps scraper suite (168 tests)",
        "cmd": [PYTHON, "-m", "pytest", "tests/unit/gmaps", "-q"],
        "expected_count": 168,
        "env": {"PYTHONPATH": f"{REPO_ROOT / 'packages' / 'scrapers' / 'google_maps' / 'src'};{REPO_ROOT}"},
    },
    "osm": {
        "description": "OpenMap spatial engine tests (31 tests)",
        "cmd": [PYTHON, "-m", "unittest", "discover", "-s", "tests/unit/osm", "-p", "test_*.py"],
        "expected_count": 31,
        "env": {},
    },
    "agents": {
        "description": "Autonomous AI agent behavior tests (12 tests)",
        "cmd": [PYTHON, "-m", "unittest", "tests/integration/test_agent_behaviors.py"],
        "expected_count": 12,
        "env": {},
    },
    "e2e": {
        "description": "End-to-End pipeline & saga integration tests (16 tests)",
        "cmd": [PYTHON, "-m", "pytest", "tests/e2e", "-q"],
        "expected_count": 16,
        "env": {"PYTHONPATH": f"{REPO_ROOT / 'packages' / 'scrapers' / 'google_maps' / 'src'};{REPO_ROOT}"},
    },
}


def run_suite(name: str, config: dict, verbose: bool = False) -> dict:
    print(f"\n{'─'*60}")
    print(f"Running: {config['description']}")
    print(f"Command: {' '.join(config['cmd'])}")
    print(f"{'─'*60}")

    env = os.environ.copy()
    env.update(config.get("env", {}))
    if "PYTHONPATH" not in env:
        env["PYTHONPATH"] = str(REPO_ROOT)

    result = subprocess.run(
        config["cmd"], capture_output=True, text=True, cwd=str(REPO_ROOT), env=env
    )

    stdout = result.stdout + "\n" + result.stderr
    passed = 0
    failed = 0
    total = 0

    # Parse counts from unittest output (e.g. "Ran 122 tests in 2.3s ... OK")
    ran_match = re.search(r"Ran (\d+) tests", stdout)
    if ran_match:
        total = int(ran_match.group(1))
        if result.returncode == 0:
            passed = total
            failed = 0
        else:
            failures_match = re.search(r"FAILED \((?:failures=(\d+))?(?:, )?(?:errors=(\d+))?\)", stdout)
            f_count = int(failures_match.group(1) or 0) if failures_match else 1
            e_count = int(failures_match.group(2) or 0) if failures_match else 0
            failed = f_count + e_count
            passed = total - failed
    else:
        # Parse pytest output (e.g. "168 passed in 54.15s")
        passed_match = re.search(r"(\d+) passed", stdout)
        failed_match = re.search(r"(\d+) failed", stdout)
        if passed_match:
            passed = int(passed_match.group(1))
        if failed_match:
            failed = int(failed_match.group(1))
        total = passed + failed

    status = "PASS" if result.returncode == 0 and failed == 0 else "FAIL"

    if status == "PASS":
        print(f"  ✅ PASS — {passed}/{total or config['expected_count']} tests passed")
    else:
        print(f"  ❌ FAIL — {passed} passed, {failed} failed")
        print(stdout[-2000:])

    return {
        "suite": name,
        "description": config["description"],
        "status": status,
        "passed": passed,
        "failed": failed,
        "total": total or config["expected_count"],
        "returncode": result.returncode,
    }


def main():
    parser = argparse.ArgumentParser(description="DataExtraction Test Validation Gate")
    parser.add_argument("--suite", choices=list(SUITES.keys()) + ["all"], default="all")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    suites_to_run = list(SUITES.keys()) if args.suite == "all" else [args.suite]

    print(f"\n{'='*60}")
    print("DataExtraction — Monorepo Quality Gate")
    print(f"{'='*60}")
    print(f"Suites: {', '.join(suites_to_run)}")

    results = []
    for suite_name in suites_to_run:
        result = run_suite(suite_name, SUITES[suite_name], verbose=args.verbose)
        results.append(result)

    total_passed = sum(r["passed"] for r in results)
    total_failed = sum(r["failed"] for r in results)
    total_tests = sum(r["total"] for r in results)
    all_pass = all(r["status"] == "PASS" for r in results)

    print(f"\n{'='*60}")
    print("GATE SUMMARY:")
    print(f"  Total tests:  {total_tests}")
    print(f"  Total passed: {total_passed} ({(total_passed/total_tests*100) if total_tests else 0:.1f}%)")
    print(f"  Total failed: {total_failed}")

    for r in results:
        icon = "✅" if r["status"] == "PASS" else "❌"
        print(f"  {icon} {r['suite']:10} {r['passed']}/{r['total']} ({r['description']})")

    # Save gate report
    gate_report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "authorized": all_pass,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "total_tests": total_tests,
        "suites": results,
    }
    report_path = REPO_ROOT / "scripts/migration/gate_report.json"
    report_path.write_text(json.dumps(gate_report, indent=2))

    if all_pass:
        print(f"\n{'='*60}")
        print("✅ QUALITY GATE PASSED — 100% GREEN — ALL SUITES VERIFIED")
        print(f"{'='*60}\n")
        sys.exit(0)
    else:
        print(f"\n{'='*60}")
        print("❌ QUALITY GATE FAILED — Fix test failures before proceeding")
        print(f"{'='*60}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
