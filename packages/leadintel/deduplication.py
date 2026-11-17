"""
LeadIntel deduplication and matching helpers.
Reuses domain deduplication algorithms for fast canonical key resolution.
"""

import re
from typing import Optional


GENERIC_DOMAINS = {
    "facebook.com",
    "linkedin.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "google.com",
    "github.com",
    "wixsite.com",
    "wordpress.com",
    "blogspot.com",
    "sites.google.com",
}

COMPANY_SUFFIXES = {
    "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation",
    "co", "company", "pvt", "private", "plc", "gmbh", "sa", "ag"
}


def normalize_string(val: Optional[str]) -> str:
    if not val:
        return ""
    cleaned = re.sub(r"[^\w\s]", "", str(val).lower())
    words = cleaned.split()
    if words and words[-1] in COMPANY_SUFFIXES:
        words = words[:-1]
    return " ".join(words)


def clean_domain(domain: Optional[str]) -> str:
    if not domain:
        return ""
    d = domain.lower().strip()
    if d.startswith("http://"):
        d = d[7:]
    elif d.startswith("https://"):
        d = d[8:]
    d = d.split("/")[0].split(":")[0]
    if d.startswith("www."):
        d = d[4:]
    return d


def generate_company_match_key(name: str, domain: Optional[str] = None, phone: Optional[str] = None) -> str:
    """Generate deterministic composite key for deduplication."""
    norm_name = normalize_string(name)
    cdomain = clean_domain(domain)
    cphone = re.sub(r"\D", "", phone or "")[-10:] if phone else ""

    if cdomain and cdomain not in GENERIC_DOMAINS:
        return f"domain:{cdomain}"
    if cdomain and norm_name:
        return f"dom_name:{cdomain}:{norm_name}"
    if cphone and norm_name:
        return f"phone_name:{cphone}:{norm_name}"
    return f"name:{norm_name}"


def generate_person_match_key(full_name: str, org_name: Optional[str] = None, email: Optional[str] = None) -> str:
    """Generate deterministic key for person deduplication."""
    norm_name = normalize_string(full_name)
    if email and "@" in email:
        return f"email:{email.lower().strip()}"
    if org_name:
        norm_org = normalize_string(org_name)
        return f"name_org:{norm_name}:{norm_org[:20]}"
    return f"name:{norm_name}"
