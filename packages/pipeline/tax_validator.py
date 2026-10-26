"""
OneExtraction — Tax ID Validator
Provides comprehensive, evidence-based validation for US Employer Identification
Numbers (EIN) and Mexican Registro Federal de Contribuyentes (RFC).
Includes official IRS campus prefix rules and SAT personality screening.
"""

import re
from typing import Any, Dict, Optional

# ─────────────────────────────────────────────────────────────────────────────
# US EIN Validation
# ─────────────────────────────────────────────────────────────────────────────

# Official IRS Campus Prefix Table:
# Prefixes allocated by IRS for internal revenue districts, campuses, and online assignment.
VALID_IRS_EIN_PREFIXES = {
    # Andover
    "10", "12",
    # Atlanta
    "20", "22",
    # Austin
    "05", "06", "11", "13", "14", "16", "21", "23", "25", "26", "27",
    "45", "46", "47", "51", "52", "54", "55", "56", "57", "58", "59",
    "65", "71", "72", "73", "74", "75", "76", "77", "80", "81", "82",
    "83", "84", "85", "86", "87", "88", "90", "91", "92", "93", "94",
    "95", "98", "99",
    # Brookhaven
    "01", "02", "03", "04", "50",
    # Cincinnati
    "30", "32", "35", "36", "37", "38", "61",
    # Fresno
    "15", "24",
    # Kansas City
    "40", "44",
    # Memphis
    "62", "64",
    # Ogden
    "41", "42", "43", "63", "89",
    # Philadelphia
    "33", "34", "39", "48", "60", "66", "67", "68",
    # Internet (current national allocation)
    "20", "26", "27", "45", "46", "47", "81", "82", "83", "84", "85", "86", "87", "88",
    # Small Business Administration
    "31",
}

# Prefixes explicitly NEVER assigned by the IRS
DISALLOWED_IRS_EIN_PREFIXES = {
    "00", "07", "08", "09", "17", "18", "19", "28", "29", "49",
    "69", "70", "78", "79",
}

EIN_FORMATTED_RE = re.compile(r"^\d{2}-\d{7}$")


def validate_ein(ein_raw: Optional[Any]) -> Dict[str, Any]:
    """
    Validate a US Employer Identification Number (EIN).

    Checks:
    1. Null/Empty detection
    2. Format normalisation (strips hyphens and whitespace)
    3. Length = exactly 9 numeric digits
    4. Reject repetitive/dummy numbers (e.g. 000000000, 111111111)
    5. Official IRS campus prefix allocation validation
    """
    result = {
        "raw": str(ein_raw).strip() if ein_raw is not None else None,
        "clean": None,
        "formatted": None,
        "prefix": None,
        "is_valid": False,
        "reason": "MISSING",
    }

    if not ein_raw:
        return result

    s = str(ein_raw).strip()
    clean = re.sub(r"\D", "", s)

    if len(clean) != 9:
        result["clean"] = clean
        result["reason"] = f"INVALID_LENGTH (expected 9 digits, got {len(clean)})"
        return result

    result["clean"] = clean
    prefix = clean[:2]
    result["prefix"] = prefix
    result["formatted"] = f"{prefix}-{clean[2:]}"

    # Reject dummy / repetitive patterns
    if len(set(clean)) == 1:
        result["reason"] = "REPETITIVE_DUMMY_DIGITS"
        return result

    if prefix in DISALLOWED_IRS_EIN_PREFIXES or prefix not in VALID_IRS_EIN_PREFIXES:
        result["reason"] = f"INVALID_IRS_PREFIX ({prefix} is not an authorized IRS campus code)"
        return result

    result["is_valid"] = True
    result["reason"] = "VALID_IRS_EIN"
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Mexico RFC Validation
# ─────────────────────────────────────────────────────────────────────────────

RFC_MORAL_REGEX = re.compile(r"^[A-ZÑ&]{3}[0-9]{2}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])[A-Z0-9]{3}$")
RFC_FISICA_REGEX = re.compile(r"^[A-ZÑ&]{4}[0-9]{2}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])[A-Z0-9]{3}$")
GENERIC_RFCS = {"XAXX010101000", "XEXX010101000", "XAXX01010100", "XEXX01010100"}


def validate_rfc(rfc_raw: Optional[Any]) -> Dict[str, Any]:
    """
    Validate a Mexican RFC (Registro Federal de Contribuyentes).

    Checks:
    1. Null/Empty detection
    2. Strips punctuation, whitespace, and normalizes uppercase
    3. Length check: 12 chars (Moral) or 13 chars (Física)
    4. RegEx compliance for SAT legal personality format
    5. Flags generic tax identifiers (XAXX010101000)
    """
    result = {
        "raw": str(rfc_raw).strip() if rfc_raw is not None else None,
        "clean": None,
        "is_valid": False,
        "rfc_type": None,
        "is_generic": False,
        "reason": "MISSING",
    }

    if not rfc_raw:
        return result

    clean = re.sub(r"[\s\-_./]", "", str(rfc_raw)).upper()
    result["clean"] = clean

    if clean in GENERIC_RFCS:
        result["is_valid"] = True
        result["is_generic"] = True
        result["rfc_type"] = "GENERIC"
        result["reason"] = "GENERIC_PUBLIC_RFC"
        return result

    if len(clean) == 12:
        if RFC_MORAL_REGEX.match(clean):
            result["is_valid"] = True
            result["rfc_type"] = "MORAL"
            result["reason"] = "VALID_RFC_MORAL"
            return result
        result["reason"] = "INVALID_RFC_MORAL_SYNTAX"
        return result

    if len(clean) == 13:
        if RFC_FISICA_REGEX.match(clean):
            result["is_valid"] = True
            result["rfc_type"] = "FISICA"
            result["reason"] = "VALID_RFC_FISICA"
            return result
        result["reason"] = "INVALID_RFC_FISICA_SYNTAX"
        return result

    result["reason"] = f"INVALID_LENGTH (expected 12 or 13 chars, got {len(clean)})"
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Unified Tax ID Dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def validate_tax_id(tax_id: Optional[Any], country: str = "US") -> Dict[str, Any]:
    """
    Unified validation interface for corporate tax identifiers.

    Args:
        tax_id:  Raw string value of the tax identifier
        country: 'US' (EIN) or 'MX' (RFC)
    """
    c = str(country).strip().upper()
    if c == "MX":
        res = validate_rfc(tax_id)
        res["country"] = "MX"
        res["identifier_type"] = "RFC"
        return res

    res = validate_ein(tax_id)
    res["country"] = "US"
    res["identifier_type"] = "EIN"
    return res
