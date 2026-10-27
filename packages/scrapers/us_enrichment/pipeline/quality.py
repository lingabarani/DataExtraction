"""
Data quality scoring engine for US B2B pipeline (0-100).
Same scoring dimensions as Mexico pipeline for cross-market parity.
"""

from ..models.company import USCanonicalCompany, USAddress


def calculate_data_quality_score(company: USCanonicalCompany) -> int:
    """
    Computes a 0-100 quality score for a US company record.

    Weights (mirrors Mexico pipeline):
    - Company Name (Legal/Trade): 20 pts
    - Location / Address:         15 pts
    - Industry / NAICS Code:      15 pts
    - EIN (valid):                10 pts
    - Website / Domain:           10 pts
    - Phone (valid):              10 pts
    - Email (valid):              10 pts
    - Source Provenance:          10 pts
    """
    score = 0

    # 1. Company Name (20 pts)
    if company.legal_name and company.trade_name:
        score += 20
    elif company.legal_name or company.trade_name:
        score += 15

    # 2. Location / Address (15 pts)
    addr = company.address
    if not isinstance(addr, USAddress):
        addr = USAddress(**(addr or {}))
    loc_points = 0
    if addr.state or addr.state_code:
        loc_points += 5
    if addr.city:
        loc_points += 3
    if addr.zip_code and len(str(addr.zip_code)) == 5:
        loc_points += 3
    if company.latitude is not None and company.longitude is not None:
        loc_points += 4
    score += min(loc_points, 15)

    # 3. Industry / NAICS (15 pts)
    if company.naics_code and company.industry:
        score += 15
    elif company.naics_code or company.sic_code or company.industry:
        score += 10

    # 4. EIN (10 pts) — equivalent to Mexico RFC
    if company.ein and _is_valid_ein(company.ein):
        score += 10
    elif company.cik or company.cage_code or company.uei:
        score += 5  # Partial credit for other IDs

    # 5. Website / Domain (10 pts)
    if company.domain and company.website:
        score += 10
    elif company.domain or company.website:
        score += 7

    # 6. Phone (10 pts)
    if company.phone and _is_valid_us_phone(company.phone):
        score += 10
    elif company.phones:
        score += 7

    # 7. Email (10 pts)
    if company.email:
        score += 10
    elif company.emails:
        score += 7

    # 8. Source Provenance (10 pts)
    if len(company.source_records) >= 2:
        score += 10
    elif len(company.source_records) == 1:
        score += 7

    return min(max(score, 0), 100)


def _is_valid_ein(ein: str) -> bool:
    """Validate US Employer Identification Number format: XX-XXXXXXX."""
    if not ein:
        return False
    clean = ein.replace("-", "").strip()
    return clean.isdigit() and len(clean) == 9


def _is_valid_us_phone(phone: str) -> bool:
    """Validate US phone format: +1XXXXXXXXXX."""
    if not phone:
        return False
    clean = "".join(c for c in phone if c.isdigit())
    return len(clean) in (10, 11)
