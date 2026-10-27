"""
Name parsing and splitting utilities for Mexican/Spanish names.
"""

import re
import unicodedata
from typing import Tuple, Optional


COMPOUND_FIRST_NAMES = {
    "juan carlos", "maria jose", "luis miguel", "jose luis", "maria del carmen",
    "juan manuel", "jose manuel", "ana maria", "maria guadalupe", "jose antonio",
    "maria elena", "carlos alberto", "jorge luis", "miguel angel", "victor manuel",
    "francisco javier", "jesus alberto", "marco antonio", "pedro luis", "juan pablo",
}

PREPOSITIONS = {"de", "del", "la", "las", "los", "y", "san", "santa"}


def remove_accents(text: str) -> str:
    """Removes accents and diacritics."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


def clean_name_string(raw_name: Optional[str]) -> str:
    """Removes professional prefixes (Lic., Ing., Dr., C.P., etc.) and punctuation."""
    if not raw_name:
        return ""
    cleaned = str(raw_name).strip()
    # Strip professional title prefixes
    cleaned = re.sub(r"^(lic\.|ing\.|dr\.|dra\.|c\.p\.|mtro\.|mtra\.|prof\.|abog\.)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[,\-_./]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def parse_mexican_full_name(raw_name: Optional[str]) -> Tuple[Optional[str], Optional[str], str]:
    """
    Parses a Mexican full name into (first_name, last_name, cleaned_full_name).
    
    Examples:
    - 'Lic. Carlos González Rodríguez' -> ('Carlos', 'González Rodríguez', 'Carlos González Rodríguez')
    - 'Juan Carlos Pérez López' -> ('Juan Carlos', 'Pérez López', 'Juan Carlos Pérez López')
    - 'Maria del Carmen Morales' -> ('Maria del Carmen', 'Morales', 'Maria del Carmen Morales')
    """
    clean_full = clean_name_string(raw_name)
    if not clean_full:
        return None, None, ""

    tokens = clean_full.split()
    if len(tokens) == 1:
        return tokens[0], None, clean_full

    if len(tokens) == 2:
        return tokens[0], tokens[1], clean_full

    # Check for 2-word compound first names
    first_two = f"{tokens[0]} {tokens[1]}".lower()
    first_two_no_accent = remove_accents(first_two)
    
    if first_two_no_accent in COMPOUND_FIRST_NAMES:
        first_name = f"{tokens[0]} {tokens[1]}"
        last_name = " ".join(tokens[2:])
        return first_name, last_name, clean_full

    # Check for 'Maria del Carmen', 'Ana de la Cruz' etc.
    if len(tokens) >= 4 and tokens[1].lower() in PREPOSITIONS and tokens[2].lower() in PREPOSITIONS:
        first_name = " ".join(tokens[:3])
        last_name = " ".join(tokens[3:])
        return first_name, last_name, clean_full

    # Default: first word as first name, remaining as surnames
    first_name = tokens[0]
    last_name = " ".join(tokens[1:])
    return first_name, last_name, clean_full
