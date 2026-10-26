"""
OneExtraction — Geographic Boundary & Postal Code Normalizer
Validates physical coordinate boundaries, detects inverted lat/lon pairs,
preserves non-contiguous US territories (Alaska, Hawaii, Puerto Rico, Guam),
and normalizes truncated postal codes with leading-zero restoration.
"""

import re
from typing import Any, Dict, Optional, Tuple

US_ZIP5_RE = re.compile(r"^\d{5}$")
US_ZIP9_RE = re.compile(r"^\d{5}-\d{4}$")
MX_CP_RE   = re.compile(r"^\d{5}$")


def normalize_postal_code(postal_code: Optional[Any], country: str = "US") -> Optional[str]:
    """
    Normalizes postal codes and restores leading zeroes dropped by spreadsheet parsers.

    Examples:
        '1234'   (US) -> '01234'   (Massachusetts / New England)
        '2138'   (US) -> '02138'   (Cambridge, MA)
        '1000'   (MX) -> '01000'   (Álvaro Obregón, CDMX)
        '123456789' (US) -> '12345-6789'
    """
    if postal_code is None:
        return None

    raw = str(postal_code).strip()
    if not raw:
        return None

    c = str(country).strip().upper()

    if c == "MX":
        digits = re.sub(r"\D", "", raw)
        if 1 <= len(digits) <= 5:
            cp = digits.zfill(5)
            # Mexican postal codes run from 01000 to 99999
            if cp == "00000":
                return None
            return cp
        return None

    # Default: US
    # Check if already valid ZIP+4 (e.g. 12345-6789)
    if US_ZIP9_RE.match(raw):
        return raw

    digits = re.sub(r"\D", "", raw)

    # 9-digit unformatted -> ZIP+4
    if len(digits) == 9:
        return f"{digits[:5]}-{digits[5:]}"

    # 1 to 5 digits -> restore dropped leading zeroes
    if 1 <= len(digits) <= 5:
        zip5 = digits.zfill(5)
        # Disallow 00000 (invalid US ZIP)
        if zip5 == "00000":
            return None
        return zip5

    return None


format_postal_code = normalize_postal_code


def validate_coordinates(
    latitude: Optional[Any],
    longitude: Optional[Any],
    country: str = "US",
) -> Dict[str, Any]:
    """
    Validate physical and geographic coordinate boundaries.

    Checks:
    1. Parse float values cleanly
    2. Global physical limits (-90 <= lat <= 90, -180 <= lon <= 180)
    3. Inverted coordinate detection (lat/lon swapped)
    4. Geographic boundary membership without rejecting valid edge cases
       (e.g., Alaska, Hawaii, Puerto Rico, Guam for US).
    """
    result = {
        "latitude": None,
        "longitude": None,
        "is_valid": False,
        "is_swapped": False,
        "region": None,
        "reason": "MISSING",
    }

    if latitude is None or longitude is None:
        return result

    try:
        lat = float(latitude)
        lon = float(longitude)
    except (ValueError, TypeError):
        result["reason"] = "NON_NUMERIC_COORDINATES"
        return result

    result["latitude"] = lat
    result["longitude"] = lon

    c = str(country).strip().upper()

    # 1. Swapped coordinate detection:
    # Case A: Latitude exceeds global physical bounds [-90, 90], but swapping puts both into valid global ranges
    if (abs(lat) > 90.0 and abs(lat) <= 180.0) and abs(lon) <= 90.0:
        result["is_swapped"] = True
        result["suggested_latitude"] = lon
        result["suggested_longitude"] = lat
        result["reason"] = "SWAPPED_COORDINATES (latitude > 90°, appears to be longitude)"
        return result

    # Case B: For US/MX, latitude is positive (North) and longitude is negative (West).
    # If passed with lat < 0 and lon > 0, swapping puts them into plausible North American bounds
    if (c in ("US", "MX")) and (lat < 0.0 and lon > 0.0):
        swapped_lat = lon
        swapped_lon = lat
        if -90.0 <= swapped_lat <= 90.0 and -180.0 <= swapped_lon <= 180.0:
            result["is_swapped"] = True
            result["suggested_latitude"] = swapped_lat
            result["suggested_longitude"] = swapped_lon
            result["reason"] = "SWAPPED_COORDINATES (latitude and longitude appear inverted)"
            return result

    # 2. Global physical boundaries
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        result["reason"] = "OUT_OF_GLOBAL_BOUNDS"
        return result

    # 3. Null Island dummy default (0, 0)
    if abs(lat) < 0.0001 and abs(lon) < 0.0001:
        result["reason"] = "NULL_ISLAND_PLACEHOLDER"
        return result

    # 3. Country-specific region classification
    if c == "US":
        # Contiguous United States (CONUS)
        if 24.0 <= lat <= 50.0 and -125.0 <= lon <= -66.0:
            result["is_valid"] = True
            result["region"] = "CONUS"
            result["reason"] = "VALID_CONUS"
            return result

        # Alaska (AK) - includes Aleutian Islands crossing 180th meridian
        if (51.0 <= lat <= 72.0) and (-180.0 <= lon <= -129.0 or 170.0 <= lon <= 180.0):
            result["is_valid"] = True
            result["region"] = "ALASKA"
            result["reason"] = "VALID_ALASKA"
            return result

        # Hawaii (HI)
        if 18.0 <= lat <= 29.0 and (-179.0 <= lon <= -154.0):
            result["is_valid"] = True
            result["region"] = "HAWAII"
            result["reason"] = "VALID_HAWAII"
            return result

        # Puerto Rico & US Virgin Islands
        if 17.5 <= lat <= 19.0 and -68.0 <= lon <= -64.5:
            result["is_valid"] = True
            result["region"] = "PUERTO_RICO_USVI"
            result["reason"] = "VALID_TERRITORY"
            return result

        # Guam & Northern Mariana Islands
        if 13.0 <= lat <= 21.0 and 144.0 <= lon <= 146.5:
            result["is_valid"] = True
            result["region"] = "GUAM_CNMI"
            result["reason"] = "VALID_TERRITORY"
            return result

        result["reason"] = "OUT_OF_US_BOUNDS"
        return result

    if c == "MX":
        if 14.0 <= lat <= 33.0 and -119.0 <= lon <= -86.0:
            result["is_valid"] = True
            result["region"] = "MEXICO"
            result["reason"] = "VALID_MEXICO"
            return result
        result["reason"] = "OUT_OF_MEXICO_BOUNDS"
        return result

    # Generic valid global coordinates for other countries
    result["is_valid"] = True
    result["region"] = "INTERNATIONAL"
    result["reason"] = "VALID_GLOBAL_COORDINATES"
    return result
