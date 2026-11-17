"""
Disposable email domain list.
Reuses and extends the canonical DISPOSABLE_DOMAINS from packages.pipeline.contact_validator.
"""

from typing import Set

try:
    from packages.pipeline.contact_validator import DISPOSABLE_DOMAINS as _CANONICAL_DISPOSABLE
except ImportError:
    _CANONICAL_DISPOSABLE = set()

LEADINTEL_EXTRA_DISPOSABLE: Set[str] = {
    "mailinator.com",
    "guerrillamail.com",
    "tempmail.com",
    "10minutemail.com",
    "trashmail.com",
    "yopmail.com",
    "dispostable.com",
    "throwawaymail.com",
    "sharklasers.com",
    "guerrillamailblock.com",
    "grr.la",
    "spam4.me",
    "fakemailgenerator.com",
    "emailondeck.com",
    "temp-mail.org",
    "getairmail.com",
    "maildrop.cc",
    "inboxkitten.com",
    "mohmal.com",
    "mytemp.email",
}

DISPOSABLE_DOMAINS: Set[str] = set(_CANONICAL_DISPOSABLE) | LEADINTEL_EXTRA_DISPOSABLE


def is_disposable_domain(domain: str) -> bool:
    """Check if a domain or its apex domain is a known disposable email provider."""
    if not domain:
        return False
    clean = domain.lower().strip()
    if clean in DISPOSABLE_DOMAINS:
        return True
    parts = clean.split(".")
    if len(parts) > 2:
        apex = ".".join(parts[-2:])
        if apex in DISPOSABLE_DOMAINS:
            return True
    return False
