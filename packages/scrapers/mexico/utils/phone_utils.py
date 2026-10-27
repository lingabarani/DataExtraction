"""
Mexican phone number normalization and validation utilities.
"""

import re
from typing import Optional


def clean_phone(raw_phone: Optional[str]) -> Optional[str]:
    """Extracts digits from phone string, handling optional leading + sign."""
    if not raw_phone:
        return None
    s = str(raw_phone).strip()
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return None
    # If starts with 52 (country code) and has 12 digits, strip country code to get 10-digit national number
    if len(digits) == 12 and digits.startswith("52"):
        digits = digits[2:]
    # If 11 digits starting with 1 (some legacy mobile formats e.g. 521XXXXXXXXXX -> digits = 10 digits)
    elif len(digits) == 13 and digits.startswith("521"):
        digits = digits[3:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits


def is_valid_mx_phone(phone: Optional[str]) -> bool:
    """Checks if phone resolves to a 10-digit Mexican number with valid area code (first digit 2-9)."""
    digits = clean_phone(phone)
    if not digits or len(digits) != 10:
        return False
    # Mexican 10-digit numbers cannot start with 0 or 1
    return digits[0] in "23456789"


def format_mx_phone_e164(phone: Optional[str]) -> Optional[str]:
    """Formats phone to E.164 format (+52XXXXXXXXXX)."""
    digits = clean_phone(phone)
    if digits and is_valid_mx_phone(digits):
        return f"+52{digits}"
    return None


def format_mx_phone_national(phone: Optional[str]) -> Optional[str]:
    """Formats phone to Mexican standard 10-digit national format."""
    digits = clean_phone(phone)
    if digits and is_valid_mx_phone(digits):
        return digits
    return None
