"""
Data validation engine for Mexican B2B company and decision-maker records.
"""

import re
from typing import Dict, Any, List, Optional
from ..models.company import CanonicalCompany, Address
from ..models.person import DecisionMaker
from ..utils.rfc_utils import is_valid_rfc, is_generic_rfc
from ..utils.phone_utils import is_valid_mx_phone
from ..utils.address_utils import is_valid_postal_code, is_valid_coordinates, normalize_state


class ValidationResult:
    def __init__(self, is_valid: bool, errors: List[str], warnings: List[str]):
        self.is_valid = is_valid
        self.errors = errors
        self.warnings = warnings

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def is_valid_email_syntax(email: Optional[str]) -> bool:
    """Validates basic RFC email syntax."""
    if not email or not isinstance(email, str):
        return False
    return bool(re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email.strip()))


def is_valid_domain(domain: Optional[str]) -> bool:
    """Validates root domain format."""
    if not domain or not isinstance(domain, str):
        return False
    clean_d = domain.strip().lower()
    return bool("." in clean_d and len(clean_d) >= 4 and not clean_d.startswith(".") and not clean_d.endswith("."))


def get_company_validation_flags(company: CanonicalCompany) -> Dict[str, bool]:
    """
    Computes standard boolean validation flags for a company record.
    """
    addr = company.address if isinstance(company.address, Address) else Address(**(company.address or {}))
    postal_code = addr.postal_code if addr else None

    has_valid_name = bool((company.legal_name and len(company.legal_name.strip()) > 1) or (company.trade_name and len(company.trade_name.strip()) > 1))
    has_valid_rfc = bool(company.rfc and is_valid_rfc(company.rfc) and not is_generic_rfc(company.rfc))
    has_valid_phone = bool(company.phone and is_valid_mx_phone(company.phone))
    has_valid_postal = bool(postal_code and is_valid_postal_code(postal_code))
    has_valid_domain = bool(is_valid_domain(company.domain))
    has_valid_email = bool(is_valid_email_syntax(company.email))
    has_valid_mx = bool(has_valid_domain and company.domain and ("." in company.domain))

    return {
        "name_valid": has_valid_name,
        "rfc_valid": has_valid_rfc,
        "phone_valid": has_valid_phone,
        "postal_code_valid": has_valid_postal,
        "domain_valid": has_valid_domain,
        "email_syntax_valid": has_valid_email,
        "dns_mx_valid": has_valid_mx,
    }


def get_person_validation_flags(person: DecisionMaker) -> Dict[str, bool]:
    """
    Computes standard boolean validation flags for a decision-maker lead.
    """
    email_syntax = bool(is_valid_email_syntax(person.work_email))
    dns_mx = bool(person.company_domain and is_valid_domain(person.company_domain))
    phone_valid = bool(person.direct_phone and is_valid_mx_phone(person.direct_phone))

    return {
        "email_syntax_valid": email_syntax,
        "dns_mx_valid": dns_mx,
        "phone_valid": phone_valid,
    }


def validate_company(company: CanonicalCompany) -> ValidationResult:
    """
    Validates a canonical company record against strict business rules.
    """
    errors = []
    warnings = []

    # 1. Company Name check (Mandatory)
    if not company.legal_name and not company.trade_name:
        errors.append("MISSING_COMPANY_NAME: Record must have at least legal_name or trade_name")

    # 2. RFC check (Optional, but if present must be valid)
    if company.rfc:
        if not is_valid_rfc(company.rfc):
            warnings.append(f"INVALID_RFC_FORMAT: '{company.rfc}' is not a valid Mexican RFC")
        elif is_generic_rfc(company.rfc):
            warnings.append(f"GENERIC_RFC: '{company.rfc}' is a generic RFC")

    # 3. Address / State check
    addr = company.address
    if isinstance(addr, Address):
        if addr.state and not normalize_state(addr.state):
            warnings.append(f"UNRECOGNIZED_STATE: '{addr.state}' does not map to a recognized Mexican state")
        if addr.postal_code and not is_valid_postal_code(addr.postal_code):
            warnings.append(f"INVALID_POSTAL_CODE: '{addr.postal_code}' is not a valid 5-digit postal code")

    # 4. Coordinates check
    if company.latitude is not None or company.longitude is not None:
        if not is_valid_coordinates(company.latitude, company.longitude):
            warnings.append(
                f"OUT_OF_BOUNDS_COORDINATES: lat={company.latitude}, lng={company.longitude} is outside Mexico bounds"
            )

    # 5. Phone check
    if company.phone and not is_valid_mx_phone(company.phone):
        warnings.append(f"INVALID_PHONE_FORMAT: '{company.phone}' is not a valid 10-digit Mexican number")

    # Record is considered structurally valid if no fatal errors exist
    is_valid = len(errors) == 0

    return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)


def validate_person(person: DecisionMaker) -> ValidationResult:
    """
    Validates a decision-maker person record.
    """
    errors = []
    warnings = []

    if not person.full_name and not person.first_name and not person.last_name:
        errors.append("MISSING_PERSON_NAME: Record must have a valid full_name, first_name or last_name")

    if person.work_email and not is_valid_email_syntax(person.work_email):
        warnings.append(f"INVALID_EMAIL_SYNTAX: '{person.work_email}'")

    if person.direct_phone and not is_valid_mx_phone(person.direct_phone):
        warnings.append(f"INVALID_PHONE_FORMAT: '{person.direct_phone}'")

    is_valid = len(errors) == 0
    return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)
