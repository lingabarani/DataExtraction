"""
RFC (Registro Federal de Contribuyentes) normalization and validation utilities.
"""

import re
from typing import Optional, Tuple


# Regex for Persona Moral (12 chars): 3 letters + 6 digits (YYMMDD) + 3 homoclave chars
RFC_MORAL_REGEX = re.compile(r"^[A-ZÑ&]{3}[0-9]{2}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])[A-Z0-9]{3}$")

# Regex for Persona Física (13 chars): 4 letters + 6 digits (YYMMDD) + 3 homoclave chars
RFC_FISICA_REGEX = re.compile(r"^[A-ZÑ&]{4}[0-9]{2}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])[A-Z0-9]{3}$")

GENERIC_RFCS = {"XAXX010101000", "XEXX010101000", "XAXX01010100", "XEXX01010100"}


def clean_rfc(rfc_raw: Optional[str]) -> Optional[str]:
    """Cleans whitespace, hyphens, and standardizes RFC string to uppercase."""
    if not rfc_raw:
        return None
    cleaned = re.sub(r"[\s\-_./]", "", str(rfc_raw)).upper()
    return cleaned if cleaned else None


def is_valid_rfc(rfc: Optional[str]) -> bool:
    """Checks if the given string matches valid Mexican RFC syntax."""
    cleaned = clean_rfc(rfc)
    if not cleaned:
        return False
    if len(cleaned) == 12:
        return bool(RFC_MORAL_REGEX.match(cleaned))
    elif len(cleaned) == 13:
        return bool(RFC_FISICA_REGEX.match(cleaned))
    return False


def is_generic_rfc(rfc: Optional[str]) -> bool:
    """Checks if RFC is a generic public/foreign RFC (XAXX010101000 / XEXX010101000)."""
    cleaned = clean_rfc(rfc)
    return cleaned in GENERIC_RFCS if cleaned else False


def get_rfc_type(rfc: Optional[str]) -> Optional[str]:
    """
    Returns the legal personality type of the RFC.
    Returns: 'MORAL', 'FISICA', 'GENERIC', or None if invalid.
    """
    cleaned = clean_rfc(rfc)
    if not cleaned or not is_valid_rfc(cleaned):
        return None
    if is_generic_rfc(cleaned):
        return "GENERIC"
    if len(cleaned) == 12:
        return "MORAL"
    elif len(cleaned) == 13:
        return "FISICA"
    return None
