"""
DataExtraction — OpenStreetMap Scraper Package
==============================================
Exports OSM geospatial extraction engines.
"""

from packages.scrapers.open_map.osm_scraper import OsmScraper, run

__all__ = ["OsmScraper", "run"]
