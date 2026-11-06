#!/usr/bin/env python3
"""
DataExtraction — Migration 005: Apollo.io MDM Schema Alignment
==============================================================
Convenience runner invoking Migration 008 from the scripts/migration directory.
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from packages.infrastructure.migrations.apply_008_migration import run_migration_008

if __name__ == "__main__":
    success = run_migration_008()
    sys.exit(0 if success else 1)
