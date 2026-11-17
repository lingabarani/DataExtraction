"""
LinkedIn scraping and public profile / company discovery package.
Strictly defaults to public ld+json discovery with polite token-bucket pacing.
Authenticated Voyager mode is disabled unless explicitly enabled via LINKEDIN_AUTH_ENABLED=true.
"""

from .client import Blocked, RateLimited, AuthExpired, Transient, LinkedInHttpClient
from .public_profile import parse_public_profile
from .company import parse_public_company
from .discover import discover_linkedin_entities

__all__ = [
    "Blocked",
    "RateLimited",
    "AuthExpired",
    "Transient",
    "LinkedInHttpClient",
    "parse_public_profile",
    "parse_public_company",
    "discover_linkedin_entities",
]
