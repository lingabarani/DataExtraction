"""
DataExtraction - OpenMap Engine Package Bridge
Allows `from openmap_engine import ...` to resolve directly to `packages.scrapers.open_map`.
"""

from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent / "open_map")]

from open_map import *

