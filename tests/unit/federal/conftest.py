"""
Pytest configuration for Federal & Open Data tests in OneExtraction.
Injects packages/scrapers/us_enrichment and packages/infrastructure cleanly.
"""

import asyncio
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parents[3]
US_ENRICH_DIR = ROOT_DIR / "packages" / "scrapers" / "us_enrichment"
INFRA_DIR = ROOT_DIR / "packages" / "infrastructure"

for p in [str(US_ENRICH_DIR), str(INFRA_DIR), str(ROOT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)
