"""
Pytest configuration for Google Maps unit tests in OneExtraction.
Injects packages/scrapers/google_maps/src into sys.path cleanly.
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
GMAPS_SRC = ROOT_DIR / "packages" / "scrapers" / "google_maps" / "src"
INFRA_DIR = ROOT_DIR / "packages" / "infrastructure"

for p in [str(GMAPS_SRC), str(INFRA_DIR), str(ROOT_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

