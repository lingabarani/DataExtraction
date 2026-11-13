"""
DataExtraction — OpenStreetMap Scraper Package
==============================================
Lazily exports OSM geospatial extraction engines via PEP 562 __getattr__
so importing lightweight config/taxonomy modules never eagerly loads pandas.
"""

import importlib


def __getattr__(name: str):
    if name in ("OsmScraper", "run"):
        mod = importlib.import_module("packages.scrapers.open_map.osm_scraper")
        return getattr(mod, name)
    return importlib.import_module(f"packages.scrapers.open_map.{name}")


__all__ = ["OsmScraper", "run"]
