"""
Data normalization engine for Mexican company data.
Standardizes company names, legal suffixes, emails, phones, domains, addresses, and employee counts.
"""

import re
from typing import Optional, Tuple, Dict, Any
from urllib.parse import urlparse
from ..utils.address_utils import normalize_state, clean_postal_code, remove_accents
from ..utils.phone_utils import clean_phone, format_mx_phone_e164
from ..utils.rfc_utils import clean_rfc, is_valid_rfc, get_rfc_type


# Common Mexican corporate legal suffixes for normalization
LEGAL_SUFFIX_PATTERNS = [
    r"\bS\.?\s*A\.?\s*P\.?\s*I\.?\s*D\.?\s*E\s*C\.?\s*V\.?\b",
    r"\bS\.?\s*A\.?\s*P\.?\s*I\.?\b",
    r"\bS\.?\s*A\.?\s*D\.?\s*E\s*C\.?\s*V\.?\b",
    r"\bS\.?\s*A\.?\s*B\.?\s*D\.?\s*E\s*C\.?\s*V\.?\b",
    r"\bS\.?\s*A\.?\s*B\.?\b",
    r"\bS\.?\s*A\.?\b",
    r"\bS\.?\s*D\.?\s*E\s*R\.?\s*L\.?\s*D\.?\s*E\s*C\.?\s*V\.?\b",
    r"\bS\.?\s*D\.?\s*E\s*R\.?\s*L\.?\b",
    r"\bS\.?\s*R\.?\s*L\.?\s*D\.?\s*E\s*C\.?\s*V\.?\b",
    r"\bS\.?\s*R\.?\s*L\.?\b",
    r"\bS\.?\s*A\.?\s*S\.?\s*D\.?\s*E\s*C\.?\s*V\.?\b",
    r"\bS\.?\s*A\.?\s*S\.?\b",
    r"\bS\.?\s*C\.?\s*D\.?\s*E\s*R\.?\s*L\.?\b",
    r"\bS\.?\s*C\.?\s*D\.?\s*E\s*P\.?\s*DE\s*C\.?\s*V\.?\b",
    r"\bS\.?\s*C\.?\b",
    r"\bA\.?\s*C\.?\b",
    r"\bS\.?\s*N\.?\s*C\.?\b",
    r"\bS\.?\s*C\.?\s*S\.?\b",
    r"\bE\.?\s*I\.?\s*R\.?\s*L\.?\b",
    r"\bI\.?\s*A\.?\s*P\.?\b",
    r"\bS\.?\s*C\.?\s*L\.?\b",
]

COMPILED_SUFFIX_REGEX = re.compile(
    "|".join(LEGAL_SUFFIX_PATTERNS),
    re.IGNORECASE
)

# Placeholders for invalid emails
INVALID_EMAIL_PATTERNS = {
    "no_tiene@correo.com",
    "sin_correo@dominio.com",
    "no_proporcionado@correo.com",
    "noaplica@correo.com",
    "sd@sd.com",
    "correo@correo.com",
    "test@test.com",
}


def normalize_company_name(raw_name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Normalizes company name for comparison while preserving formatted display name.
    
    Returns:
        (original_display_name, normalized_comparison_name)
    """
    if not raw_name:
        return None, None

    cleaned = str(raw_name).strip()
    if not cleaned:
        return None, None

    # Collapse multiple whitespaces
    cleaned = re.sub(r"\s+", " ", cleaned)

    # Comparison normalization:
    # 1. Remove accents
    comp = remove_accents(cleaned.upper())
    # 2. Remove legal suffixes
    comp = COMPILED_SUFFIX_REGEX.sub("", comp)
    # 3. Remove punctuation and special characters
    comp = re.sub(r"[^A-Z0-9\s]", " ", comp)
    # 4. Collapse spaces
    comp = re.sub(r"\s+", " ", comp).strip()

    return cleaned, comp if comp else cleaned.upper()


def normalize_email(raw_email: Optional[str]) -> Optional[str]:
    """Cleans and validates email syntax."""
    if not raw_email:
        return None
    email_clean = str(raw_email).strip().lower()
    # Filter placeholder emails
    if email_clean in INVALID_EMAIL_PATTERNS or "notiene" in email_clean:
        return None
    # RFC 5322-compliant syntax check
    email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if re.match(email_regex, email_clean):
        return email_clean
    return None


def normalize_website(raw_url: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Normalizes website URL and extracts root domain.
    
    Returns:
        (normalized_url, domain)
    """
    if not raw_url:
        return None, None
    url_clean = str(raw_url).strip()
    if not url_clean or url_clean.lower() in ("no", "sin", "n/a", "no tiene", "none"):
        return None, None

    if not (url_clean.startswith("http://") or url_clean.startswith("https://")):
        url_clean = "https://" + url_clean

    try:
        parsed = urlparse(url_clean)
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            domain = netloc[4:]
        else:
            domain = netloc

        # Filter invalid domains
        if "." not in domain or len(domain) < 4:
            return None, None

        normalized_url = f"https://{netloc}{parsed.path}".rstrip("/")
        return normalized_url, domain
    except Exception:
        return None, None


def parse_employee_range(range_str: Optional[str]) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """
    Parses employee range string (e.g., from DENUE or SIEM) into (min_count, max_count, source_text).
    Examples:
    - '0 a 5 personas' -> (0, 5, '0 a 5 personas')
    - '6 a 10 personas' -> (6, 10, '6 a 10 personas')
    - '11 a 30 personas' -> (11, 30, '11 a 30 personas')
    - '31 a 50 personas' -> (31, 50, '31 a 50 personas')
    - '51 a 100 personas' -> (51, 100, '51 a 100 personas')
    - '101 a 250 personas' -> (101, 250, '101 a 250 personas')
    - '251 y más personas' -> (251, None, '251 y más personas')
    """
    if not range_str:
        return None, None, None

    text = str(range_str).strip().lower()
    
    # Check 'X a Y' pattern
    match_range = re.search(r"(\d+)\s*(?:a|-)\s*(\d+)", text)
    if match_range:
        return int(match_range.group(1)), int(match_range.group(2)), range_str

    # Check 'X y más' / '> X' pattern
    match_plus = re.search(r"(\d+)\s*(?:y\s*m[aá]s|\+)", text)
    if match_plus:
        return int(match_plus.group(1)), None, range_str

    # Exact number
    if text.isdigit():
        val = int(text)
        return val, val, range_str

    return None, None, range_str
