"""
DataExtraction — Google Maps Services Module
"""

from .taxonomy import ServiceTaxonomyClassifier, TAXONOMY_VERSION, TAXONOMY_RULES
from .extractor import GoogleMapsServiceExtractor

__all__ = [
    "ServiceTaxonomyClassifier",
    "GoogleMapsServiceExtractor",
    "TAXONOMY_VERSION",
    "TAXONOMY_RULES",
]
