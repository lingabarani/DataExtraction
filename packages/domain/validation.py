"""
DataExtraction — Domain Enterprise Validation Engine
====================================================
Unified enterprise validation framework implementing:
  1. 5-Tier Contact Intelligence:
     - Tier 1: RFC 5322 Syntax Regex
     - Tier 2: MX DNS Validation & DNS resolution
     - Tier 3: Disposable Domain Blacklisting
     - Tier 4: SMTP Mailbox Handshake Verification
     - Tier 5: ITU-T E.164 Phone Normalization & US Area Code Verification
  2. Statutory Tax Identifier Validation:
     - US Employer Identification Number (EIN) with IRS campus allocation prefix validation
     - Mexican Registro Federal de Contribuyentes (RFC) with Modulo-11 check digit verification
  3. Geospatial Validation:
     - Postal Code / ZIP+4 / CP standardization
     - Lat/Lng bounding box and coordinate consistency
  4. Company & Domain Extraction:
     - Registered domain isolation via Public Suffix List
"""

import os
import re
import socket
import smtplib
from typing import Any, Dict, List, Optional, Tuple

# Re-exporting core functions from contact, tax, and geo validators
from packages.pipeline.contact_validator import (
    extract_registered_domain,
    validate_email,
    validate_phone,
    normalise_linkedin,
    validate_contact,
    contact_is_usable,
    lead_score_from_contact,
    DISPOSABLE_DOMAINS,
    ROLE_PREFIXES,
)

ROLE_BASED_PREFIXES = ROLE_PREFIXES
from packages.pipeline.tax_validator import (
    validate_ein,
    validate_rfc,
    validate_tax_id,
    VALID_IRS_EIN_PREFIXES,
    DISALLOWED_IRS_EIN_PREFIXES,
)
from packages.pipeline.geo_validator import (
    normalize_postal_code,
    validate_coordinates,
)

__all__ = [
    # Contact
    "extract_registered_domain",
    "validate_email",
    "validate_phone",
    "normalise_linkedin",
    "validate_contact",
    "contact_is_usable",
    "lead_score_from_contact",
    "DISPOSABLE_DOMAINS",
    "ROLE_BASED_PREFIXES",
    # Tax ID
    "validate_ein",
    "validate_rfc",
    "validate_tax_id",
    "VALID_IRS_EIN_PREFIXES",
    "DISALLOWED_IRS_EIN_PREFIXES",
    # Geo
    "normalize_postal_code",
    "validate_coordinates",
]
