"""
Discovery Source Adapters.
Encapsulates individual discovery channels: Local DB, Google Maps, CMS, State Registry,
Web Search, Website Crawl, LinkedIn Public, and Enrichment.
"""

from packages.discovery.sources.base import SourceAdapter
from packages.discovery.sources.cms_care_compare import CMSCareCompareSource
from packages.discovery.sources.enrichment import EnrichmentSource
from packages.discovery.sources.google_maps import GoogleMapsSource
from packages.discovery.sources.linkedin_public import LinkedInPublicSource
from packages.discovery.sources.local_db import LocalDBSource
from packages.discovery.sources.state_registry import StateRegistrySource
from packages.discovery.sources.web_search import WebSearchSource
from packages.discovery.sources.website_crawl import WebsiteCrawlSource

__all__ = [
    "SourceAdapter",
    "LocalDBSource",
    "GoogleMapsSource",
    "CMSCareCompareSource",
    "StateRegistrySource",
    "WebSearchSource",
    "WebsiteCrawlSource",
    "LinkedInPublicSource",
    "EnrichmentSource",
]
