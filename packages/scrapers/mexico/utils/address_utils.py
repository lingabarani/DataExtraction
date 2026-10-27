"""
Address, Mexican state normalization, postal code, and coordinate utilities.
"""

import re
import unicodedata
from typing import Optional, Tuple, Dict


def remove_accents(text: str) -> str:
    """Removes accents and diacritics from a string."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


# Canonical 32 Mexican Federal Entities mapping
MEXICO_STATES: Dict[str, Dict[str, str]] = {
    "01": {"name": "Aguascalientes", "abbr": "AGS"},
    "02": {"name": "Baja California", "abbr": "BC"},
    "03": {"name": "Baja California Sur", "abbr": "BCS"},
    "04": {"name": "Campeche", "abbr": "CAMP"},
    "05": {"name": "Coahuila", "abbr": "COAH"},
    "06": {"name": "Colima", "abbr": "COL"},
    "07": {"name": "Chiapas", "abbr": "CHIS"},
    "08": {"name": "Chihuahua", "abbr": "CHIH"},
    "09": {"name": "Ciudad de México", "abbr": "CDMX"},
    "10": {"name": "Durango", "abbr": "DGO"},
    "11": {"name": "Guanajuato", "abbr": "GTO"},
    "12": {"name": "Guerrero", "abbr": "GRO"},
    "13": {"name": "Hidalgo", "abbr": "HGO"},
    "14": {"name": "Jalisco", "abbr": "JAL"},
    "15": {"name": "México", "abbr": "MEX"},
    "16": {"name": "Michoacán", "abbr": "MICH"},
    "17": {"name": "Morelos", "abbr": "MOR"},
    "18": {"name": "Nayarit", "abbr": "NAY"},
    "19": {"name": "Nuevo León", "abbr": "NL"},
    "20": {"name": "Oaxaca", "abbr": "OAX"},
    "21": {"name": "Puebla", "abbr": "PUE"},
    "22": {"name": "Querétaro", "abbr": "QRO"},
    "23": {"name": "Quintana Roo", "abbr": "QROO"},
    "24": {"name": "San Luis Potosí", "abbr": "SLP"},
    "25": {"name": "Sinaloa", "abbr": "SIN"},
    "26": {"name": "Sonora", "abbr": "SON"},
    "27": {"name": "Tabasco", "abbr": "TAB"},
    "28": {"name": "Tamaulipas", "abbr": "TAMPS"},
    "29": {"name": "Tlaxcala", "abbr": "TLAX"},
    "30": {"name": "Veracruz", "abbr": "VER"},
    "31": {"name": "Yucatán", "abbr": "YUC"},
    "32": {"name": "Zacatecas", "abbr": "ZAC"},
}

# Alias dictionary mapping variants to canonical names
STATE_ALIASES: Dict[str, str] = {
    # 01
    "aguascalientes": "Aguascalientes",
    "ags": "Aguascalientes",
    "01": "Aguascalientes",
    # 02
    "baja california": "Baja California",
    "baja california norte": "Baja California",
    "bc": "Baja California",
    "bcn": "Baja California",
    "02": "Baja California",
    # 03
    "baja california sur": "Baja California Sur",
    "bcs": "Baja California Sur",
    "03": "Baja California Sur",
    # 04
    "campeche": "Campeche",
    "camp": "Campeche",
    "04": "Campeche",
    # 05
    "coahuila": "Coahuila",
    "coahuila de zaragoza": "Coahuila",
    "coah": "Coahuila",
    "05": "Coahuila",
    # 06
    "colima": "Colima",
    "col": "Colima",
    "06": "Colima",
    # 07
    "chiapas": "Chiapas",
    "chis": "Chiapas",
    "07": "Chiapas",
    # 08
    "chihuahua": "Chihuahua",
    "chih": "Chihuahua",
    "08": "Chihuahua",
    # 09
    "ciudad de mexico": "Ciudad de México",
    "cdmx": "Ciudad de México",
    "distrito federal": "Ciudad de México",
    "df": "Ciudad de México",
    "d.f.": "Ciudad de México",
    "mexico d.f.": "Ciudad de México",
    "09": "Ciudad de México",
    # 10
    "durango": "Durango",
    "dgo": "Durango",
    "10": "Durango",
    # 11
    "guanajuato": "Guanajuato",
    "gto": "Guanajuato",
    "11": "Guanajuato",
    # 12
    "guerrero": "Guerrero",
    "gro": "Guerrero",
    "12": "Guerrero",
    # 13
    "hidalgo": "Hidalgo",
    "hgo": "Hidalgo",
    "13": "Hidalgo",
    # 14
    "jalisco": "Jalisco",
    "jal": "Jalisco",
    "14": "Jalisco",
    # 15
    "mexico": "México",
    "estado de mexico": "México",
    "edomex": "México",
    "edo mex": "México",
    "edo. de mexico": "México",
    "mex": "México",
    "15": "México",
    # 16
    "michoacan": "Michoacán",
    "michoacan de ocampo": "Michoacán",
    "mich": "Michoacán",
    "16": "Michoacán",
    # 17
    "morelos": "Morelos",
    "mor": "Morelos",
    "17": "Morelos",
    # 18
    "nayarit": "Nayarit",
    "nay": "Nayarit",
    "18": "Nayarit",
    # 19
    "nuevo leon": "Nuevo León",
    "nl": "Nuevo León",
    "n.l.": "Nuevo León",
    "19": "Nuevo León",
    # 20
    "oaxaca": "Oaxaca",
    "oax": "Oaxaca",
    "20": "Oaxaca",
    # 21
    "puebla": "Puebla",
    "pue": "Puebla",
    "21": "Puebla",
    # 22
    "queretaro": "Querétaro",
    "queretaro de arteaga": "Querétaro",
    "qro": "Querétaro",
    "22": "Querétaro",
    # 23
    "quintana roo": "Quintana Roo",
    "qroo": "Quintana Roo",
    "q. roo": "Quintana Roo",
    "23": "Quintana Roo",
    # 24
    "san luis potosi": "San Luis Potosí",
    "slp": "San Luis Potosí",
    "s.l.p.": "San Luis Potosí",
    "24": "San Luis Potosí",
    # 25
    "sinaloa": "Sinaloa",
    "sin": "Sinaloa",
    "25": "Sinaloa",
    # 26
    "sonora": "Sonora",
    "son": "Sonora",
    "26": "Sonora",
    # 27
    "tabasco": "Tabasco",
    "tab": "Tabasco",
    "27": "Tabasco",
    # 28
    "tamaulipas": "Tamaulipas",
    "tamps": "Tamaulipas",
    "28": "Tamaulipas",
    # 29
    "tlaxcala": "Tlaxcala",
    "tlax": "Tlaxcala",
    "29": "Tlaxcala",
    # 30
    "veracruz": "Veracruz",
    "veracruz de ignacio de la llave": "Veracruz",
    "ver": "Veracruz",
    "30": "Veracruz",
    # 31
    "yucatan": "Yucatán",
    "yuc": "Yucatán",
    "31": "Yucatán",
    # 32
    "zacatecas": "Zacatecas",
    "zac": "Zacatecas",
    "32": "Zacatecas",
}


def normalize_state(raw_state: Optional[str]) -> Optional[str]:
    """Normalizes Mexican state name or abbreviation to canonical official name."""
    if not raw_state:
        return None
    cleaned = remove_accents(str(raw_state).strip().lower())
    cleaned = re.sub(r"[\s\.\-]+", " ", cleaned).strip()
    return STATE_ALIASES.get(cleaned)


def get_state_code(state_name: Optional[str]) -> Optional[str]:
    """Returns 2-digit INEGI/ISO state code for a given state name (e.g., '09' for CDMX)."""
    norm = normalize_state(state_name)
    if not norm:
        return None
    for code, data in MEXICO_STATES.items():
        if data["name"] == norm:
            return code
    return None


def clean_postal_code(raw_cp: Optional[str]) -> Optional[str]:
    """Extracts 5-digit Mexican postal code."""
    if not raw_cp:
        return None
    digits = re.sub(r"[^\d]", "", str(raw_cp).strip())
    if len(digits) == 4:
        # Some CPs starting with 0 (e.g. 01000 in CDMX) lose the leading zero in Excel/CSV
        digits = "0" + digits
    if len(digits) == 5:
        return digits
    return None


def is_valid_postal_code(cp: Optional[str]) -> bool:
    """Validates 5-digit postal code."""
    cleaned = clean_postal_code(cp)
    return cleaned is not None and len(cleaned) == 5 and cleaned.isdigit()


def is_valid_coordinates(lat: Optional[float], lng: Optional[float]) -> bool:
    """
    Validates geographic coordinates for Mexican territory.
    Latitude roughly: 14.0 to 33.0
    Longitude roughly: -119.0 to -86.0
    """
    if lat is None or lng is None:
        return False
    try:
        lat_f = float(lat)
        lng_f = float(lng)
        return 14.0 <= lat_f <= 33.5 and -119.0 <= lng_f <= -86.0
    except (ValueError, TypeError):
        return False
