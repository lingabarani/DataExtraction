from typing import Any, Dict

def calculate_data_quality_score(company: Dict[str, Any]) -> int:
    """
    Calculates a transparent data quality score (0 to 100) based strictly on
    verified, explicitly populated fields. Inferred data or placeholders get 0 points.
    
    Rubric:
    +20 legal / company name
    +15 website / domain
    +15 address (street/city/state/zip)
    +10 phone
    +10 industry / description / business_category
    +10 NAICS / SIC code
    +10 registration identifier (EIN, CIK, UEI, registration_number)
    +5 employee information
    +5 source provenance (valid source_records)
    """
    score = 0
    
    # 1. Company Name (+20)
    legal_name = company.get("legal_name") or company.get("trade_name") or company.get("dba_name")
    if legal_name and isinstance(legal_name, str) and len(legal_name.strip()) > 1:
        score += 20
        
    # 2. Website / Domain (+15)
    domain = company.get("domain") or company.get("website")
    if domain and isinstance(domain, str) and "." in domain and len(domain.strip()) > 3:
        score += 15
        
    # 3. Address (+15)
    addr = company.get("address", {}) or {}
    has_street = bool(addr.get("street"))
    has_city = bool(addr.get("city"))
    has_state = bool(addr.get("state") or addr.get("state_code"))
    has_zip = bool(addr.get("zip_code"))
    
    # Needs at least city + state or street + city/state
    if (has_street and (has_city or has_state)) or (has_city and has_state):
        score += 15
    elif has_city or has_state or has_zip:
        score += 8
        
    # 4. Phone (+10)
    phones = company.get("phones", [])
    if phones and isinstance(phones, list) and len(phones) > 0:
        if any(bool(p.get("value")) for p in phones if isinstance(p, dict)):
            score += 10
            
    # 5. Industry / Description (+10)
    industry = company.get("industry") or company.get("business_category") or company.get("description")
    if industry and isinstance(industry, str) and len(industry.strip()) > 2:
        score += 10
        
    # 6. NAICS / SIC (+10)
    naics = company.get("naics_code")
    sic = company.get("sic_code")
    if (naics and str(naics).strip()) or (sic and str(sic).strip()):
        score += 10
        
    # 7. Registration Identifier (+10)
    if (
        company.get("ein") or 
        company.get("cik") or 
        company.get("uei") or 
        company.get("duns") or 
        (company.get("registration_number") and str(company.get("registration_number")).strip()) or
        (company.get("state_registration_number") and str(company.get("state_registration_number")).strip())
    ):
        score += 10
        
    # 8. Employee information (+5)
    if company.get("employee_count") is not None or company.get("employee_count_min") is not None:
        score += 5
        
    # 9. Source provenance (+5)
    source_records = company.get("source_records", [])
    if source_records and isinstance(source_records, list) and len(source_records) > 0:
        score += 5
        
    return min(score, 100)
