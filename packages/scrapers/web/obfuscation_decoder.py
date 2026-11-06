"""
DataExtraction — Email Obfuscation Decoder & Multi-Layer Extractor
=================================================================
Extracted and enhanced from FORGE web scraping engine.
Decodes:
  - Cloudflare data-cfemail XOR cipher
  - HTML numeric & hex entity encoding (&#64;, &#x40;, &#46;, &#x2e;)
  - Textual bracketed obfuscation: [at], (at), [dot], (dot)
  - Mailto anchor links and target attributes
  - JSON-LD Schema.org structured business data
  - HTML comments and footer signatures
Filters:
  - Binary asset files (.png, .css, .js)
  - Generic synthetic test domains (example.com, sentry.io, wixpress.com)
"""

import html as html_module
import json
import logging
import re
from typing import Any, Iterable, List, Optional, Set

logger = logging.getLogger("dataextraction.scrapers.obfuscation_decoder")

# ── Extraction Regular Expressions ────────────────────────────────────────────

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)

_MAILTO_RE = re.compile(
    r"mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})",
    re.IGNORECASE,
)

_CF_EMAIL_RE = re.compile(r'data-cfemail="([a-fA-F0-9]+)"')

_OBFUSCATED_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+\s*[\[\(]\s*(?:at|AT)\s*[\]\)]\s*[a-zA-Z0-9.\-]+\s*[\[\(]\s*(?:dot|DOT)\s*[\]\)]\s*[a-zA-Z]{2,}",
    re.IGNORECASE,
)

_HTML_ENTITY_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+(?:&#64;|&#x40;)[a-zA-Z0-9.\-]+(?:&#46;|&#x2e;)[a-zA-Z]{2,}",
    re.IGNORECASE,
)

_JSONLD_SCRIPT_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)

_HTML_COMMENT_RE = re.compile(r"<!--(.*?)-->", re.DOTALL)

# ── Blacklisted False-Positive Domains & File Extensions ───────────────────────

FAKE_EMAIL_DOMAINS: Set[str] = {
    "example.com",
    "email.com",
    "domain.com",
    "yoursite.com",
    "yourdomain.com",
    "company.com",
    "test.com",
    "placeholder.com",
    "sentry.io",
    "wixpress.com",
    "wordpress.org",
    "wordpress.com",
    "w3.org",
    "schema.org",
    "googleapis.com",
    "gravatar.com",
    "wp.com",
    "sentry-next.wixpress.com",
    "changedetection.io",
    "myshopify.com",
}

DISALLOWED_ASSET_EXTENSIONS: Set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
    ".mp4", ".mp3", ".pdf", ".zip"
}


def decode_cf_email(encoded: str) -> Optional[str]:
    """
    Decodes Cloudflare's XOR-based __cf_email__ protection string.
    The first 2 hex digits represent the XOR key; each subsequent pair is XORed with this key.
    """
    if not encoded or len(encoded) < 4:
        return None
    try:
        key = int(encoded[:2], 16)
        decoded_chars = []
        for i in range(2, len(encoded), 2):
            decoded_chars.append(chr(int(encoded[i : i + 2], 16) ^ key))
        decoded = "".join(decoded_chars).lower().strip()
        if "@" in decoded and "." in decoded.split("@")[-1]:
            return decoded
    except (ValueError, IndexError):
        pass
    return None


def decode_html_entities(text: str) -> str:
    """Unescapes HTML numeric and named entities (e.g. &#64; -> @, &amp; -> &)."""
    if not text:
        return ""
    return html_module.unescape(text)


def is_valid_email_candidate(email: str) -> bool:
    """
    Validates candidate email formatting and rejects synthetic test domains,
    asset filenames, and invalid lengths.
    """
    if not email or "@" not in email:
        return False

    email = email.lower().strip().strip(".,:;\"'()[]{}")
    if len(email) > 254:
        return False

    parts = email.split("@")
    if len(parts) != 2:
        return False

    local_part, domain_part = parts
    if not local_part or not domain_part:
        return False

    if "." not in domain_part:
        return False

    if domain_part in FAKE_EMAIL_DOMAINS:
        return False

    # Check for binary file extensions erroneously parsed as emails
    for ext in DISALLOWED_ASSET_EXTENSIONS:
        if email.endswith(ext):
            return False

    return bool(_EMAIL_RE.match(email))


def extract_mailto_emails(html: str) -> Set[str]:
    """Layer 1: Extracts clean emails from mailto: anchor links."""
    emails = set()
    for match in _MAILTO_RE.findall(html or ""):
        candidate = match.lower().strip()
        if is_valid_email_candidate(candidate):
            emails.add(candidate)
    return emails


def extract_cf_obfuscated_emails(html: str) -> Set[str]:
    """Layer 2: Decodes Cloudflare data-cfemail cipher blocks."""
    emails = set()
    for encoded in _CF_EMAIL_RE.findall(html or ""):
        decoded = decode_cf_email(encoded)
        if decoded and is_valid_email_candidate(decoded):
            emails.add(decoded)
    return emails


def extract_text_obfuscated_emails(html: str) -> Set[str]:
    """Layer 3: Decodes [at]/[dot] and HTML entity encoded emails."""
    emails = set()
    if not html:
        return emails

    # 1. Unescape full HTML entities first
    unescaped = decode_html_entities(html)
    for match in _EMAIL_RE.findall(unescaped):
        candidate = match.lower().strip()
        if is_valid_email_candidate(candidate):
            emails.add(candidate)

    # 2. Match entity emails before unescaping
    for match in _HTML_ENTITY_EMAIL_RE.findall(html):
        decoded = decode_html_entities(match).lower().strip()
        if is_valid_email_candidate(decoded):
            emails.add(decoded)

    # 3. Match [at] / (at) / [dot] / (dot) textual obfuscation
    for match in _OBFUSCATED_EMAIL_RE.findall(html):
        cleaned = re.sub(r"\s*[\[\(]\s*(?:at|AT)\s*[\]\)]\s*", "@", match)
        cleaned = re.sub(r"\s*[\[\(]\s*(?:dot|DOT)\s*[\]\)]\s*", ".", cleaned)
        cleaned = cleaned.lower().strip()
        if is_valid_email_candidate(cleaned):
            emails.add(cleaned)

    return emails


def _walk_jsonld(data: Any, results: Set[str]) -> None:
    """Recursively walks parsed JSON-LD structures extracting email addresses."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() == "email" and isinstance(value, str):
                cleaned = value.lower().strip().removeprefix("mailto:")
                if is_valid_email_candidate(cleaned):
                    results.add(cleaned)
            else:
                _walk_jsonld(value, results)
    elif isinstance(data, list):
        for item in data:
            _walk_jsonld(item, results)


def extract_jsonld_emails(html: str) -> Set[str]:
    """Layer 4: Extracts schema.org business email addresses from JSON-LD blocks."""
    emails: Set[str] = set()
    if not html:
        return emails

    for script_block in _JSONLD_SCRIPT_RE.findall(html):
        try:
            parsed = json.loads(script_block)
            _walk_jsonld(parsed, emails)
        except (json.JSONDecodeError, ValueError):
            continue
    return emails


def extract_footer_and_comment_emails(html: str) -> Set[str]:
    """Layer 5: Scans the footer region and raw HTML comments for hidden contacts."""
    emails: Set[str] = set()
    if not html:
        return emails

    # Footer area (last 25% of document)
    footer_start = int(len(html) * 0.75)
    footer_chunk = html[footer_start:]
    for match in _EMAIL_RE.findall(footer_chunk):
        cand = match.lower().strip()
        if is_valid_email_candidate(cand):
            emails.add(cand)

    # HTML comments throughout the document
    for comment in _HTML_COMMENT_RE.findall(html):
        for match in _EMAIL_RE.findall(comment):
            cand = match.lower().strip()
            if is_valid_email_candidate(cand):
                emails.add(cand)

    return emails


def extract_all_emails_from_html(html: str) -> Set[str]:
    """
    Executes all 5 extraction layers in sequence.
    Returns a unified set of verified, lowercased email addresses.
    """
    if not html:
        return set()

    found: Set[str] = set()
    found.update(extract_mailto_emails(html))
    found.update(extract_cf_obfuscated_emails(html))
    found.update(extract_text_obfuscated_emails(html))
    found.update(extract_jsonld_emails(html))
    found.update(extract_footer_and_comment_emails(html))
    return found

