from datetime import datetime, timezone
import uuid
from typing import Any, Dict, List, Optional

def current_iso_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()

def build_empty_company_record() -> Dict[str, Any]:
    """Returns a fresh dictionary conforming strictly to the requested standardized company JSON format."""
    now = current_iso_timestamp()
    return {
        "company_id": str(uuid.uuid4()),
        "legal_name": "",
        "trade_name": "",
        "dba_name": "",
        "normalized_name": "",
        "entity_type": "",
        "company_status": "",

        "registration_number": "",
        "state_registration_number": "",
        "ein": None,
        "uei": None,
        "duns": None,
        "cik": None,

        "description": "",
        "industry": "",
        "industry_code": "",
        "naics_code": "",
        "sic_code": "",
        "business_category": "",

        "employee_count": None,
        "employee_count_min": None,
        "employee_count_max": None,
        "employee_count_source": "",

        "revenue": None,
        "revenue_range": None,

        "address": {
            "street": "",
            "city": "",
            "state": "",
            "state_code": "",
            "zip_code": "",
            "county": "",
            "country": "United States",
            "latitude": None,
            "longitude": None
        },

        "website": "",
        "domain": "",

        "phones": [],
        "emails": [],

        "people": [],
        "executives": [],
        "directors": [],
        "founders": [],
        "officers": [],

        "source_records": [],

        "data_quality_score": 0,
        "confidence_score": 0,
        "validation_status": "UNVALIDATED",

        "last_verified_at": "",
        "created_at": now,
        "updated_at": now
    }

def build_source_record(
    source_name: str,
    source_type: str,
    source_url: str,
    source_record_id: str,
    collection_method: str = "API",
    fields_collected: Optional[List[str]] = None,
    source_status: str = "ACTIVE"
) -> Dict[str, Any]:
    """Creates a standardized source_records provenance entry."""
    return {
        "source_name": source_name,
        "source_type": source_type,
        "source_url": source_url,
        "source_record_id": str(source_record_id),
        "collection_method": collection_method,
        "fields_collected": fields_collected or [],
        "collection_timestamp": current_iso_timestamp(),
        "source_status": source_status
    }

def build_phone_entry(
    phone_number: str,
    source_name: str,
    source_url: str,
    phone_type: str = "OFFICE"
) -> Dict[str, Any]:
    return {
        "value": phone_number,
        "source": source_name,
        "source_url": source_url,
        "type": phone_type,
        "verified": False,
        "collected_at": current_iso_timestamp()
    }

def build_email_entry(
    email: str,
    source_name: str,
    source_url: str,
    email_type: str = "OFFICE"
) -> Dict[str, Any]:
    return {
        "value": email,
        "source": source_name,
        "source_url": source_url,
        "type": email_type,
        "verified": False,
        "collected_at": current_iso_timestamp()
    }
