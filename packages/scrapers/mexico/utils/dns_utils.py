"""
DNS MX inspection, mail provider detection, email pattern generator, and verification utilities.
"""

import re
import socket
import smtplib
from typing import List, Dict, Tuple, Optional
import dns.resolver
from .name_utils import remove_accents


def get_mx_records(domain: str, timeout: float = 3.0) -> List[str]:
    """
    Fetches sorted MX record hostnames for a domain.
    """
    if not domain or "." not in domain:
        return []
    clean_domain = domain.strip().lower()
    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = timeout
        resolver.timeout = timeout
        answers = resolver.resolve(clean_domain, "MX")
        mx_hosts = [str(r.exchange).rstrip(".").lower() for r in sorted(answers, key=lambda a: a.preference)]
        return mx_hosts
    except Exception:
        return []


def detect_mail_provider(mx_records: List[str]) -> str:
    """
    Detects the corporate mail provider from MX hostnames.
    Returns: 'MICROSOFT_365_OUTLOOK', 'GOOGLE_WORKSPACE', 'CUSTOM_SMTP', or 'UNKNOWN'
    """
    if not mx_records:
        return "UNKNOWN"

    for mx in mx_records:
        mx_lower = mx.lower()
        if "outlook.com" in mx_lower or "protection.outlook" in mx_lower or "microsoft" in mx_lower:
            return "MICROSOFT_365_OUTLOOK"
        if "google.com" in mx_lower or "googlemail.com" in mx_lower or "aspmx" in mx_lower:
            return "GOOGLE_WORKSPACE"
        if "zoho" in mx_lower:
            return "ZOHO_MAIL"
        if "mimecast" in mx_lower or "barracuda" in mx_lower:
            return "ENTERPRISE_GATEWAY"

    return "CUSTOM_SMTP"


def generate_email_permutations(
    first_name: Optional[str],
    last_name: Optional[str],
    domain: str,
) -> List[Tuple[str, str]]:
    """
    Generates standard corporate B2B email permutations.
    
    Returns:
        List of (email_address, pattern_name)
    """
    if not domain or not first_name:
        return []

    # Clean names (remove accents and special characters)
    f_clean = re.sub(r"[^a-z]", "", remove_accents(first_name.split()[0].lower()))
    l_tokens = [re.sub(r"[^a-z]", "", remove_accents(t.lower())) for t in (last_name or "").split()]
    l_clean = l_tokens[0] if l_tokens and l_tokens[0] else ""

    if not f_clean:
        return []

    dom = domain.strip().lower()
    permutations: List[Tuple[str, str]] = []

    if l_clean:
        # Pattern 1: first.last@domain (Most common enterprise / Microsoft 365)
        permutations.append((f"{f_clean}.{l_clean}@{dom}", "{first}.{last}"))
        # Pattern 2: f.last@domain / flast@domain
        permutations.append((f"{f_clean[0]}{l_clean}@{dom}", "{f}{last}"))
        permutations.append((f"{f_clean[0]}.{l_clean}@{dom}", "{f}.{last}"))
        # Pattern 3: first@domain
        permutations.append((f"{f_clean}@{dom}", "{first}"))
        # Pattern 4: first_last@domain
        permutations.append((f"{f_clean}_{l_clean}@{dom}", "{first}_{last}"))
        # Pattern 5: last.first@domain
        permutations.append((f"{l_clean}.{f_clean}@{dom}", "{last}.{first}"))
        # Pattern 6: firstlast@domain
        permutations.append((f"{f_clean}{l_clean}@{dom}", "{first}{last}"))
    else:
        permutations.append((f"{f_clean}@{dom}", "{first}"))

    return permutations


def verify_email_deliverability(
    email: str,
    mx_records: Optional[List[str]] = None,
    perform_smtp_handshake: bool = False,
    timeout: float = 3.0,
) -> Tuple[str, int]:
    """
    Verifies email syntax, MX record validity, and optional SMTP deliverability handshake.
    
    Returns:
        (email_status, confidence_score)
        Status: 'VERIFIED', 'PROBABLE', 'CATCH_ALL', 'UNVERIFIED', 'INVALID'
    """
    if not email or "@" not in email:
        return "INVALID", 0

    user, domain = email.split("@", 1)
    if not user or not domain or "." not in domain:
        return "INVALID", 0

    # Syntax check
    if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
        return "INVALID", 0

    if mx_records is None:
        mx_records = get_mx_records(domain, timeout=timeout)

    if not mx_records:
        return "UNVERIFIED", 20

    # If domain has valid MX records
    provider = detect_mail_provider(mx_records)
    base_confidence = 75 if provider != "UNKNOWN" else 50

    if not perform_smtp_handshake:
        return "PROBABLE", base_confidence

    # Live SMTP Handshake (Safe HELO -> MAIL FROM -> RCPT TO)
    try:
        primary_mx = mx_records[0]
        with smtplib.SMTP(primary_mx, 25, timeout=timeout) as smtp:
            smtp.helo("verify.mexico-b2b.org")
            smtp.mail("probe@mexico-b2b.org")
            code, _ = smtp.rcpt(email)
            if code == 250:
                return "VERIFIED", 95
            elif code in (550, 551, 552, 553):
                return "INVALID", 0
            else:
                return "PROBABLE", 70
    except Exception:
        # Fallback to probable if handshake times out
        return "PROBABLE", base_confidence
