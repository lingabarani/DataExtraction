import re
from typing import Dict, Optional
from urllib.parse import urlparse

US_STATES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
    "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "FLORIDA": "FL", "GEORGIA": "GA",
    "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA",
    "KANSAS": "KS", "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS", "MISSOURI": "MO",
    "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ",
    "NEW MEXICO": "NM", "NEW YORK": "NY", "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH",
    "OKLAHOMA": "OK", "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT",
    "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
    "DISTRICT OF COLUMBIA": "DC", "PUERTO RICO": "PR", "GUAM": "GU", "VIRGIN ISLANDS": "VI"
}

STATE_CODE_TO_NAME = {v: k.title() for k, v in US_STATES.items()}

# Common legal designator suffixes to strip for normalized matching
LEGAL_SUFFIXES_REGEX = re.compile(
    r'\b(inc\.?|incorporated|corp\.?|corporation|llc\.?|l\.l\.c\.?|ltd\.?|limited|co\.?|company|lp\.?|l\.p\.?|llp\.?|l\.l\.p\.?|pllc\.?|p\.c\.?|pc)\b',
    re.IGNORECASE
)

def normalize_company_name(name: Optional[str]) -> str:
    """Normalize company name: lowercase, strip legal entity suffixes, remove punctuation, collapse whitespace."""
    if not name or not isinstance(name, str):
        return ""
    cleaned = LEGAL_SUFFIXES_REGEX.sub("", name)
    cleaned = re.sub(r'[\',.\-\&/()#@!*?":;]+', " ", cleaned)
    cleaned = re.sub(r'\s+', " ", cleaned).strip().lower()
    return cleaned

def normalize_phone(phone: Optional[str]) -> Optional[str]:
    """Normalize US phone number to E.164 format (+1XXXXXXXXXX)."""
    if not phone or not isinstance(phone, str):
        return None
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 10:
        return f"+1{digits}"
    elif len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    elif len(digits) > 7:
        return f"+{digits}"
    return None

def normalize_state(state_input: Optional[str]) -> tuple[str, str]:
    """Return (state_name, state_code). Handles both full names and 2-letter codes."""
    if not state_input or not isinstance(state_input, str):
        return ("", "")
    cleaned = state_input.strip().upper()
    if cleaned in STATE_CODE_TO_NAME:
        return (STATE_CODE_TO_NAME[cleaned], cleaned)
    if cleaned in US_STATES:
        code = US_STATES[cleaned]
        return (STATE_CODE_TO_NAME[code], code)
    return (state_input.strip().title(), "")

def normalize_zip(zip_input: Optional[str]) -> str:
    """Extract standard 5-digit US ZIP code."""
    if not zip_input or not isinstance(zip_input, str):
        return ""
    cleaned = zip_input.strip()
    match = re.match(r'^(\d{5})', cleaned)
    if match:
        return match.group(1)
    return cleaned[:5] if cleaned.isdigit() else cleaned

def normalize_domain(url_or_domain: Optional[str]) -> str:
    """Extract clean domain name without scheme, www, path, or port."""
    if not url_or_domain or not isinstance(url_or_domain, str):
        return ""
    s = url_or_domain.strip().lower()
    if not s.startswith(('http://', 'https://')):
        s = 'http://' + s
    try:
        parsed = urlparse(s)
        netloc = parsed.netloc or parsed.path
        netloc = netloc.split(':')[0]
        if netloc.startswith('www.'):
            netloc = netloc[4:]
        return netloc.strip('/')
    except Exception:
        return ""
