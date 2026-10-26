import re
from typing import Any, Dict

def generate_entity_fingerprint(company: Dict[str, Any]) -> str:
    """
    Generates a deterministic entity fingerprint based on company identifiers,
    normalized name, domain, and geographic location.
    
    Priority keys:
    1. CIK / UEI / EIN / Registration Number (if present)
    2. normalized_name + domain (if domain is present)
    3. normalized_name + state_code + city
    4. normalized_name + phone
    """
    # 1. Unique federal/state registration identifiers if available
    cik = company.get("cik")
    if cik:
        return f"cik:{str(cik).strip().lower()}"
    
    uei = company.get("uei")
    if uei:
        return f"uei:{str(uei).strip().lower()}"
    
    ein = company.get("ein")
    if ein:
        clean_ein = re.sub(r'\D', '', str(ein))
        if len(clean_ein) == 9:
            return f"ein:{clean_ein}"
    
    norm_name = company.get("normalized_name", "").strip()
    # slugify normalized name for fingerprint
    name_slug = re.sub(r'[^a-z0-9]+', '-', norm_name).strip('-') or "unnamed"
    
    domain = company.get("domain", "").strip().lower()
    if domain:
        return f"{name_slug}|{domain}"
        
    addr = company.get("address", {}) or {}
    state_code = addr.get("state_code", "").strip().lower()
    city = re.sub(r'[^a-z0-9]+', '-', addr.get("city", "").strip().lower()).strip('-')
    
    if state_code and city:
        return f"{name_slug}|{state_code}|{city}"
    
    phones = company.get("phones", [])
    if phones and isinstance(phones, list) and len(phones) > 0:
        first_phone = phones[0].get("value", "")
        clean_phone = re.sub(r'\D', '', first_phone)
        if clean_phone:
            return f"{name_slug}|{clean_phone}"
            
    if state_code:
        return f"{name_slug}|{state_code}"

    reg_num = company.get("registration_number", "").strip().lower()
    if reg_num:
        return f"{name_slug}|reg:{reg_num}"

    return name_slug
