"""
Data quality scoring engine (0-100) based on record completeness and verification.
"""

from typing import Dict, Any
from ..models.company import CanonicalCompany, Address
from ..utils.rfc_utils import is_valid_rfc
from ..utils.phone_utils import is_valid_mx_phone
from ..utils.address_utils import is_valid_postal_code


def calculate_data_quality_score(company: CanonicalCompany) -> int:
    """
    Computes a 0-100 quality score for a company record.
    
    Weights:
    - Company Name (Legal/Trade): 20 pts
    - Location / Address: 15 pts
    - Industry / SCIAN Code: 15 pts
    - RFC (valid): 10 pts
    - Website / Domain: 10 pts
    - Phone (valid): 10 pts
    - Email (valid): 10 pts
    - Source Provenance: 10 pts
    """
    score = 0

    # 1. Company Name (20 pts)
    if company.legal_name and company.trade_name:
        score += 20
    elif company.legal_name or company.trade_name:
        score += 15

    # 2. Location / Address (15 pts)
    addr = company.address if isinstance(company.address, Address) else Address(**(company.address or {}))
    loc_points = 0
    if addr.state:
        loc_points += 5
    if addr.municipality:
        loc_points += 3
    if addr.postal_code and is_valid_postal_code(addr.postal_code):
        loc_points += 3
    if company.latitude is not None and company.longitude is not None:
        loc_points += 4
    score += min(loc_points, 15)

    # 3. Industry (15 pts)
    if company.industry_code and company.industry:
        score += 15
    elif company.industry_code or company.industry:
        score += 10

    # 4. RFC (10 pts)
    if company.rfc and is_valid_rfc(company.rfc):
        score += 10

    # 5. Website / Domain (10 pts)
    if company.domain and company.website:
        score += 10
    elif company.domain or company.website:
        score += 7

    # 6. Phone (10 pts)
    if company.phone and is_valid_mx_phone(company.phone):
        score += 10
    elif company.phones and len(company.phones) > 0:
        score += 7

    # 7. Email (10 pts)
    if company.email:
        score += 10
    elif company.emails and len(company.emails) > 0:
        score += 7

    # 8. Source Provenance (10 pts)
    if len(company.source_records) >= 2:
        score += 10
    elif len(company.source_records) == 1:
        score += 7

    return min(max(score, 0), 100)
