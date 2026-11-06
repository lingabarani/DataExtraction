"""
DataExtraction — Web Scrapers Package
=====================================
Contains high-throughput async crawlers, obfuscation decoders, and site profilers.
"""

from packages.scrapers.web.obfuscation_decoder import (
    decode_cf_email,
    decode_html_entities,
    extract_all_emails_from_html,
    is_valid_email_candidate,
)
from packages.scrapers.web.email_crawler import AsyncEmailWebCrawler

__all__ = [
    "decode_cf_email",
    "decode_html_entities",
    "extract_all_emails_from_html",
    "is_valid_email_candidate",
    "AsyncEmailWebCrawler",
]

