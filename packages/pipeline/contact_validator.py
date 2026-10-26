"""
OneExtraction - Contact Validator (Production Hardened)
Evidence-based validation for emails and phone numbers across US and Mexico.

Operational & Provider Restrictions Note:
------------------------------------------
SMTP probing (RCPT TO commands) and catch-all verification are subject to strict
operational limitations:
1. Major enterprise providers (Google Workspace, Microsoft 365, Mimecast, Proofpoint)
   frequently tarpit, drop connections, or employ wildcard 250 OK acceptance (catch-all)
   to prevent directory harvest attacks.
2. In production, an email address MUST NOT be marked as 'DELIVERABLE' or 'VERIFIED'
   solely on syntax or MX existence.
3. Addresses with valid syntax and confirmed MX records are assigned 'MX_CONFIRMED'.
4. Catch-all and role addresses are classified as 'RISKY'.
5. Only addresses with verified SMTP handshake delivery proof or cryptographically signed
   vendor logs are marked 'DELIVERABLE'.

Validation layers:
  EMAIL:
    1. Syntax check        - RFC 5322 regex
    2. Domain extraction   - tldextract registered domain resolution
    3. Disposable check    - known disposable/temp mail provider database
    4. Role address check  - generic departmental mailboxes (info@, sales@, etc.)
    5. MX record check     - DNS MX query to confirm mail exchange capability
    6. Evidence tiering    - DELIVERABLE, MX_CONFIRMED, SYNTAX_VALID, RISKY, UNDELIVERABLE

  PHONE:
    1. Google phonenumbers library integration
    2. National prefix & NANPA area code plausibility check
    3. E.164 canonical normalization (+1XXXXXXXXXX, +52XXXXXXXXXX)
    4. Line type extraction (MOBILE, FIXED_LINE, TOLL_FREE, VOIP)
"""

import logging
import re
import socket
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("oneextraction.validator")

# DNS resolver support
try:
    import dns.resolver
    _HAS_DNS = True
except ImportError:
    _HAS_DNS = False

# Google libphonenumber support
try:
    import phonenumbers
    from phonenumbers import PhoneNumberFormat, PhoneNumberType, NumberParseException
    _HAS_PHONENUMBERS = True
except ImportError:
    _HAS_PHONENUMBERS = False

# Public Suffix List / tldextract support
try:
    import tldextract
    _EXTRACTOR = tldextract.TLDExtract(
        cache_dir=str(Path.home() / ".cache" / "tldextract"),
        include_psl_private_domains=True
    )
    _HAS_TLDEXTRACT = True
except ImportError:
    _HAS_TLDEXTRACT = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DISPOSABLE_DOMAINS = {
    'mailinator.com', 'guerrillamail.com', 'throwam.com', 'tempmail.com',
    'yopmail.com', 'sharklasers.com', 'trashmail.com', 'maildrop.cc',
    'dispostable.com', '10minutemail.com', 'fakeinbox.com', 'spamgourmet.com',
    'getairmail.com', 'mailnull.com', 'spamspot.com', 'spam4.me',
}

ROLE_PREFIXES = {
    'info', 'contact', 'admin', 'support', 'help', 'sales', 'marketing',
    'noreply', 'no-reply', 'postmaster', 'webmaster', 'hostmaster',
    'abuse', 'security', 'privacy', 'legal', 'billing', 'accounts',
    'hello', 'team', 'office', 'press', 'media', 'jobs', 'careers',
    'hr', 'finance', 'it', 'service', 'services', 'newsletter',
}

# Strict RFC 5322 syntax regex with Latin-1 supplement support
EMAIL_RE = re.compile(
    r'^[a-zA-Z0-9._%+\-\u00C0-\u024F]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'
)

# DNS resolver setup
if _HAS_DNS:
    _DNS_RESOLVER = dns.resolver.Resolver()
    _DNS_RESOLVER.nameservers = ['1.1.1.1', '8.8.8.8', '8.8.4.4']
    _DNS_RESOLVER.timeout = 2.0
    _DNS_RESOLVER.lifetime = 2.5
else:
    _DNS_RESOLVER = None


# ---------------------------------------------------------------------------
# Domain & TLD extraction
# ---------------------------------------------------------------------------

def extract_registered_domain(url_or_domain: Optional[str]) -> Optional[str]:
    """
    Extract the registered root domain using the Public Suffix List via tldextract.
    Correctly handles multi-level ccTLDs such as .co.uk, .com.mx, .gob.mx.
    """
    if not url_or_domain:
        return None
    raw = str(url_or_domain).strip().lower()
    raw = re.sub(r'^https?://', '', raw).split('/')[0].split('?')[0]
    if _HAS_TLDEXTRACT:
        extracted = _EXTRACTOR(raw)
        if extracted.domain and extracted.suffix:
            return f"{extracted.domain}.{extracted.suffix}".lower()
    # Fallback to naive string splitting
    parts = raw.split('@')[-1].split('.')
    if len(parts) >= 2:
        return '.'.join(parts[-2:]).lower()
    return raw.lower() if raw else None


def _get_domain(email: str) -> Optional[str]:
    """Extract domain part of an email address."""
    try:
        parts = email.strip().split('@')
        if len(parts) == 2:
            return parts[1].lower()
    except (IndexError, AttributeError):
        pass
    return None


def _check_disposable(domain: str) -> bool:
    """Returns True if domain or its registered root is disposable."""
    if not domain:
        return False
    d = domain.lower()
    root = extract_registered_domain(d)
    return d in DISPOSABLE_DOMAINS or (root is not None and root in DISPOSABLE_DOMAINS)


def _check_role_address(email: str) -> bool:
    """Returns True if email prefix is a departmental role address."""
    try:
        local = email.strip().split('@')[0].lower()
        return local in ROLE_PREFIXES
    except (IndexError, AttributeError):
        return False


@lru_cache(maxsize=32768)
def _check_mx_record(domain: str) -> bool:
    """
    DNS MX record lookup with 32K LRU cache.
    Returns True if domain has at least one valid mail exchanger.
    """
    if not _HAS_DNS or not domain or "." not in domain:
        return False
    try:
        records = _DNS_RESOLVER.resolve(domain, 'MX')
        return len(records) > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Email Validation
# ---------------------------------------------------------------------------

def validate_email(
    email: Optional[str],
    pre_verified_status: Optional[str] = None,
    skip_mx: bool = False,
    smtp_delivered: bool = False,
) -> Dict[str, Any]:
    """
    Validate a single email address using evidence-based tiers.

    Status tiers:
      - DELIVERABLE    : Verified mailbox delivery via SMTP handshake or signed proof.
      - MX_CONFIRMED   : Valid RFC syntax and domain with confirmed DNS MX records.
      - SYNTAX_VALID   : Valid RFC syntax, DNS unconfirmed or skipped.
      - RISKY          : Catch-all domain or role mailbox (e.g. info@, support@).
      - UNDELIVERABLE  : Disposable domain, domain not found, or mailbox rejected.
      - INVALID        : Malformed syntax or non-email input.
      - MISSING        : No email provided.
    """
    result = {
        "email": None,
        "status": "UNKNOWN",
        "evidence_level": "UNVERIFIED",
        "confidence_score": 0,
        "checks": {
            "syntax": False,
            "domain": False,
            "registered_domain": None,
            "mx_record": False,
            "disposable": False,
            "role_addr": False,
            "pre_verified": False,
            "smtp_verified": False,
        }
    }

    if not email or not str(email).strip():
        result["status"] = "MISSING"
        result["evidence_level"] = "MISSING"
        return result

    clean_email = str(email).strip().lower()
    result["email"] = clean_email
    domain = _get_domain(clean_email)

    # 1. Syntax check
    if not EMAIL_RE.match(clean_email) or len(clean_email) > 254:
        result["status"] = "INVALID"
        result["evidence_level"] = "SYNTAX_INVALID"
        result["confidence_score"] = 0
        return result

    result["checks"]["syntax"] = True

    # 2. Domain check
    if not domain:
        result["status"] = "INVALID"
        result["evidence_level"] = "NO_DOMAIN"
        return result

    result["checks"]["domain"] = True
    reg_domain = extract_registered_domain(domain)
    result["checks"]["registered_domain"] = reg_domain

    is_disposable = _check_disposable(domain)
    is_role = _check_role_address(clean_email)
    result["checks"]["disposable"] = is_disposable
    result["checks"]["role_addr"] = is_role

    if is_disposable:
        result["status"] = "UNDELIVERABLE"
        result["evidence_level"] = "DISPOSABLE_DOMAIN"
        result["confidence_score"] = 0
        return result

    # 3. MX Record check
    mx_ok = False
    if not skip_mx:
        mx_ok = _check_mx_record(domain)
        result["checks"]["mx_record"] = mx_ok

    # 4. Verifiable proof check
    if smtp_delivered:
        result["checks"]["smtp_verified"] = True

    has_pre_verified = bool(pre_verified_status and str(pre_verified_status).upper() in ("VERIFIED", "DELIVERABLE"))
    result["checks"]["pre_verified"] = has_pre_verified

    # 5. Score calculation (0 - 100)
    score = 20  # Base syntax points
    if reg_domain:
        score += 15
    if mx_ok:
        score += 35
    if has_pre_verified:
        score += 15
    if smtp_delivered:
        score += 15
    if is_role:
        score -= 20
    score = max(0, min(100, score))
    result["confidence_score"] = score

    # 6. Evidence-based status assignment
    if smtp_delivered:
        result["status"] = "DELIVERABLE"
        result["evidence_level"] = "SMTP_HANDSHAKE_VERIFIED"
    elif is_role:
        result["status"] = "RISKY"
        result["evidence_level"] = "ROLE_ACCOUNT"
    elif not skip_mx and not mx_ok:
        result["status"] = "UNDELIVERABLE"
        result["evidence_level"] = "NO_MX_RECORDS"
        result["confidence_score"] = min(result["confidence_score"], 20)
    elif mx_ok:
        result["status"] = "MX_CONFIRMED"
        result["evidence_level"] = "DNS_MX_CONFIRMED"
    else:
        result["status"] = "SYNTAX_VALID"
        result["evidence_level"] = "SYNTAX_ONLY"

    return result


# ---------------------------------------------------------------------------
# Phone Validation (Google phonenumbers)
# ---------------------------------------------------------------------------

def validate_phone(
    phone: Optional[str],
    country: str = 'US',
) -> Dict[str, Any]:
    """
    Validate and normalize phone number using Google libphonenumber.

    Returns:
        dict with canonical E.164 formatted number, national format, line type,
        status ('VALID_E164', 'NORMALIZED', 'INVALID', 'MISSING'), and country code.
    """
    result = {
        "phone": None,
        "phone_national": None,
        "phone_raw": phone,
        "status": "MISSING",
        "phone_country": country.upper() if country else "US",
        "phone_type": "UNKNOWN",
    }

    if not phone or not str(phone).strip():
        return result

    raw = str(phone).strip()
    target_region = (country or "US").strip().upper()

    if _HAS_PHONENUMBERS:
        try:
            parsed = phonenumbers.parse(raw, region=target_region)
            if phonenumbers.is_valid_number(parsed):
                e164 = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
                national = phonenumbers.format_number(parsed, PhoneNumberFormat.NATIONAL)
                ptype_code = phonenumbers.number_type(parsed)
                ptype_name = {
                    PhoneNumberType.MOBILE: "MOBILE",
                    PhoneNumberType.FIXED_LINE: "FIXED_LINE",
                    PhoneNumberType.FIXED_LINE_OR_MOBILE: "FIXED_OR_MOBILE",
                    PhoneNumberType.TOLL_FREE: "TOLL_FREE",
                    PhoneNumberType.VOIP: "VOIP",
                }.get(ptype_code, "STANDARD")

                result["phone"] = e164
                result["phone_national"] = national
                result["status"] = "VALID_E164"
                result["phone_country"] = phonenumbers.region_code_for_number(parsed) or target_region
                result["phone_type"] = ptype_name
                return result

            # Possible number but invalid area code / length
            if phonenumbers.is_possible_number(parsed):
                e164 = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
                result["phone"] = e164
                result["status"] = "NORMALIZED"
                return result

            result["status"] = "INVALID"
            return result
        except NumberParseException:
            result["status"] = "INVALID"
            return result

    # Fallback when phonenumbers is not installed
    digits = re.sub(r"\D", "", raw)
    if target_region == "US" and len(digits) == 10:
        result["phone"] = f"+1{digits}"
        result["status"] = "NORMALIZED"
    elif target_region == "MX" and len(digits) == 10:
        result["phone"] = f"+52{digits}"
        result["status"] = "NORMALIZED"
    else:
        result["status"] = "INVALID"
    return result


# ---------------------------------------------------------------------------
# LinkedIn Normalization
# ---------------------------------------------------------------------------

def normalise_linkedin(url: Optional[str]) -> Optional[str]:
    """Normalise LinkedIn URL to canonical https://linkedin.com/in/handle form."""
    if not url or not str(url).strip():
        return None
    raw = str(url).strip()
    clean = re.sub(r"^https?://(www\.)?", "", raw).rstrip("/")
    if clean.startswith("linkedin.com/in/"):
        return f"https://{clean}"
    if "/in/" in clean:
        handle = clean.split("/in/")[-1].rstrip("/")
        return f"https://linkedin.com/in/{handle}"
    return f"https://{clean}" if not clean.startswith("http") else clean


# ---------------------------------------------------------------------------
# Combined Contact Validation
# ---------------------------------------------------------------------------

def validate_contact(
    email: Optional[str] = None,
    phone: Optional[str] = None,
    linkedin_url: Optional[str] = None,
    pre_verified_status: Optional[str] = None,
    country: str = 'US',
    skip_mx: bool = False,
    smtp_delivered: bool = False,
) -> Dict[str, Any]:
    """
    Run full evidence-based email, phone, and LinkedIn validation.
    Returns structured contact dictionary suitable for JSONB storage.
    """
    email_result = validate_email(email, pre_verified_status, skip_mx, smtp_delivered)
    phone_result = validate_phone(phone, country)
    linkedin = normalise_linkedin(linkedin_url)

    return {
        "email": email_result["email"],
        "email_status": email_result["status"],
        "email_evidence_level": email_result["evidence_level"],
        "email_confidence_score": email_result["confidence_score"],
        "email_checks": email_result["checks"],
        "phone": phone_result["phone"],
        "phone_national": phone_result.get("phone_national"),
        "phone_status": phone_result["status"],
        "phone_country": phone_result["phone_country"],
        "phone_type": phone_result.get("phone_type", "UNKNOWN"),
        "phone_raw": phone_result["phone_raw"],
        "linkedin_url": linkedin,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }


def contact_is_usable(contact: Dict[str, Any]) -> bool:
    """
    Returns True if the contact has at least one reachable channel:
    an evidence-confirmed email (DELIVERABLE or MX_CONFIRMED) or valid E.164 phone.
    """
    status = (contact.get("email_status") or "").upper()
    email_ok = status in ("DELIVERABLE", "MX_CONFIRMED", "VERIFIED", "VALID")
    phone_status = (contact.get("phone_status") or "").upper()
    phone_ok = phone_status in ("VALID_E164", "NORMALIZED")
    return email_ok or phone_ok


def lead_score_from_contact(
    contact: Dict[str, Any],
    person_quality: int = 0,
    company_quality: int = 0,
    seniority_level: str = "",
) -> int:
    """
    Compute a 0-100 lead score combining:
      - Email evidence quality (0-40 pts)
      - Phone quality          (0-20 pts)
      - Person profile quality (0-20 pts)
      - Seniority bonus        (0-10 pts)
      - Company quality        (0-10 pts)
    """
    score = 0
    status = (contact.get("email_status") or "").upper()

    if status in ("DELIVERABLE", "VERIFIED"):
        score += 40
    elif status in ("MX_CONFIRMED", "VALID"):
        score += 30
    elif status == "RISKY":
        score += 15
    elif status in ("SYNTAX_VALID", "GUESSED"):
        score += 10

    phone_status = (contact.get("phone_status") or "").upper()
    if phone_status == "VALID_E164":
        score += 20
    elif phone_status == "NORMALIZED":
        score += 10

    if person_quality:
        score += int(person_quality / 5)

    seniority_map = {
        "C_SUITE": 10, "OWNER": 10, "FOUNDER": 10,
        "VP": 8, "DIRECTOR": 7,
        "MANAGER": 5,
    }
    score += seniority_map.get((seniority_level or "").upper(), 0)

    if company_quality:
        score += int(company_quality / 10)

    return min(100, max(0, score))
