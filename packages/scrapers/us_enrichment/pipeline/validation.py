"""
Field-level validation for US B2B company and person records.
"""

import re
from typing import Dict, Optional
from ..models.company import USCanonicalCompany, USAddress
from ..models.person import USDecisionMaker

EIN_RE = re.compile(r"^\d{2}-?\d{7}$")
US_PHONE_RE = re.compile(r"^\+?1?\d{10}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")
NAICS_RE = re.compile(r"^\d{2,6}$")
CIK_RE = re.compile(r"^\d{1,10}$")


def validate_company(company: USCanonicalCompany) -> bool:
    """Returns True if company passes minimum validation requirements."""
    if not company.legal_name or len(company.legal_name.strip()) < 2:
        return False
    if not company.address:
        return False
    addr = company.address if isinstance(company.address, USAddress) else USAddress(**(company.address or {}))
    if not addr.state and not addr.state_code and not addr.city:
        return False
    return True


def validate_person(person: USDecisionMaker) -> bool:
    """Returns True if person passes minimum validation requirements."""
    if not person.full_name or len(person.full_name.strip()) < 2:
        return False
    if not person.company_id:
        return False
    return True


def get_company_validation_flags(company: USCanonicalCompany) -> Dict[str, bool]:
    """Returns a dict of validation flags for a company record."""
    addr = company.address if isinstance(company.address, USAddress) else USAddress(**(company.address or {}))
    return {
        "has_legal_name": bool(company.legal_name),
        "has_ein": bool(company.ein and EIN_RE.match(company.ein.replace("-", "") + "-dummy")[:2] or company.ein),
        "has_cik": bool(company.cik),
        "has_cage_code": bool(company.cage_code),
        "has_naics": bool(company.naics_code and NAICS_RE.match(company.naics_code)),
        "has_sic": bool(company.sic_code),
        "has_website": bool(company.website),
        "has_domain": bool(company.domain),
        "has_phone": bool(company.phone and US_PHONE_RE.match("".join(c for c in company.phone if c.isdigit() or c == "+"))),
        "has_email": bool(company.email and EMAIL_RE.match(company.email)),
        "has_state": bool(addr.state or addr.state_code),
        "has_city": bool(addr.city),
        "has_zip": bool(addr.zip_code and ZIP_RE.match(str(addr.zip_code))),
        "has_coordinates": (company.latitude is not None and company.longitude is not None),
        "has_employee_count": (company.employee_count_min is not None),
        "multi_source": len(company.source_records) >= 2,
    }


def get_person_validation_flags(person: USDecisionMaker) -> Dict[str, bool]:
    """Returns a dict of validation flags for a person record."""
    return {
        "has_full_name": bool(person.full_name),
        "has_first_name": bool(person.first_name),
        "has_last_name": bool(person.last_name),
        "has_title": bool(person.title),
        "has_standardized_title": bool(person.standardized_title),
        "has_work_email": bool(person.work_email and EMAIL_RE.match(person.work_email)),
        "has_direct_phone": bool(person.direct_phone),
        "email_verified": person.email_status in ("VERIFIED", "PROBABLE"),
        "is_csuite": person.seniority_level in ("C_SUITE", "FOUNDER", "VP"),
        "is_active": person.is_active,
    }
