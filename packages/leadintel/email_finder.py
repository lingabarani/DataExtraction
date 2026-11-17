"""
Email candidate generator, permutation engine, and DNS MX verification.
Generates candidate corporate email patterns and assigns explicit provenance labels:
  - 'found'    (scraped directly from a page)
  - 'inferred' (generated via name patterns + DNS MX validation)
  - 'verified' (validated via SMTP handshake probe)
"""

import logging
import re
from typing import List, Optional, Set
from urllib.parse import urlparse

try:
    import dns.resolver
except ImportError:
    dns = None

from packages.discovery.models import EmailEntry

logger = logging.getLogger("dataextraction.leadintel.email_finder")

FREE_EMAIL_PROVIDERS: Set[str] = {
    "gmail.com",
    "yahoo.com",
    "hotmail.com",
    "outlook.com",
    "live.com",
    "msn.com",
    "icloud.com",
    "aol.com",
    "proton.me",
    "protonmail.com",
    "gmx.com",
    "mail.com",
    "zoho.com",
    "yandex.com",
}


def company_domain(url_or_name: Optional[str]) -> Optional[str]:
    """Extract registrable domain from URL, or slugify name and append .com if no domain present."""
    if not url_or_name or not str(url_or_name).strip():
        return None

    val = str(url_or_name).strip()

    if "://" in val or val.startswith("//") or "/" in val:
        if not val.startswith(("http://", "https://")):
            val = "https://" + val.lstrip("/")
        try:
            parsed = urlparse(val)
            host = parsed.netloc.lower()
            if ":" in host:
                host = host.split(":")[0]
            if host.startswith("www."):
                host = host[4:]
            if "." in host:
                return host
        except Exception:
            pass

    cleaned_lower = val.lower()
    if "." in cleaned_lower and " " not in cleaned_lower:
        return cleaned_lower.lstrip("www.")

    # Slugify name
    slug = re.sub(r"[^a-z0-9]", "", cleaned_lower)
    if slug:
        return f"{slug}.com"
    return None


def generate_email_candidates(first: str, last: str, domain: str) -> List[str]:
    """Generate 9 canonical corporate email permutations:
      1. first.last@domain
      2. firstlast@domain
      3. first@domain
      4. first_last@domain
      5. flast@domain
      6. firstl@domain
      7. last.first@domain
      8. f.last@domain
      9. lastfirst@domain
    """
    f = re.sub(r"[^a-z]", "", (first or "").lower())
    l = re.sub(r"[^a-z]", "", (last or "").lower())
    d = (domain or "").lower().strip()

    if not d or not (f or l):
        return []

    templates: List[str] = []

    if f and l:
        templates.append(f"{f}.{l}")
        templates.append(f"{f}{l}")
    if f:
        templates.append(f)
    if f and l:
        templates.append(f"{f}_{l}")
        templates.append(f"{f[0]}{l}")
        templates.append(f"{f}{l[0]}")
        templates.append(f"{l}.{f}")
        templates.append(f"{f[0]}.{l}")
        templates.append(f"{l}{f}")

    seen: Set[str] = set()
    candidates: List[str] = []
    for user in templates:
        email = f"{user}@{d}"
        if email not in seen:
            seen.add(email)
            candidates.append(email)

    return candidates


def check_mx_records(domain: str, timeout: float = 4.0) -> bool:
    """Check if domain resolves at least one active DNS MX record."""
    if not domain or not domain.strip() or dns is None:
        return False
    clean = domain.strip().lower()
    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = timeout
        resolver.timeout = timeout
        answers = resolver.resolve(clean, "MX")
        return len(answers) > 0
    except Exception as exc:
        logger.debug("MX lookup failed for %s: %s", clean, exc)
        return False


def infer_email_entry(
    first_name: str,
    last_name: str,
    domain: str,
    is_derived_domain: bool = False,
    source_url: Optional[str] = None,
) -> Optional[EmailEntry]:
    """Produce the top candidate corporate email with explicit 'inferred' label and confidence."""
    clean_domain = domain.lower().strip()
    if clean_domain in FREE_EMAIL_PROVIDERS:
        return None

    candidates = generate_email_candidates(first_name, last_name, clean_domain)
    if not candidates:
        return None

    top = candidates[0]
    has_mx = check_mx_records(clean_domain)

    confidence = 0.9 if (has_mx and not is_derived_domain) else (0.6 if has_mx else 0.3)

    return EmailEntry(
        value=top,
        label="inferred",
        source_url=source_url,
        confidence=confidence,
    )
