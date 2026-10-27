"""
Schema definitions and serialization helpers for CanonicalCompany.
"""

from typing import Dict, Any, List
from ..models.company import CanonicalCompany, Address, PhoneItem, EmailItem
from ..models.source_record import SourceProvenanceRecord


def deserialize_company(data: Dict[str, Any]) -> CanonicalCompany:
    """Reconstructs a CanonicalCompany instance from dictionary."""
    address_data = data.get("address") or {}
    address = Address(
        street=address_data.get("street"),
        number=address_data.get("number"),
        colony=address_data.get("colony"),
        municipality=address_data.get("municipality"),
        state=address_data.get("state"),
        postal_code=address_data.get("postal_code"),
        country=address_data.get("country", "Mexico"),
    )

    phones = [
        PhoneItem(
            value=p.get("value", ""),
            source=p.get("source", ""),
            type=p.get("type", "OFFICE"),
            verified=p.get("verified", False),
        )
        for p in data.get("phones", [])
    ]

    emails = [
        EmailItem(
            value=e.get("value", ""),
            source=e.get("source", ""),
            verified=e.get("verified", False),
        )
        for e in data.get("emails", [])
    ]

    source_records = [
        SourceProvenanceRecord(
            source=s.get("source", ""),
            source_record_id=s.get("source_record_id", ""),
            source_url=s.get("source_url", ""),
            retrieved_at=s.get("retrieved_at", ""),
            source_updated_at=s.get("source_updated_at"),
            raw_hash=s.get("raw_hash"),
        )
        for s in data.get("source_records", [])
    ]

    return CanonicalCompany(
        company_id=data.get("company_id", ""),
        legal_name=data.get("legal_name"),
        trade_name=data.get("trade_name"),
        normalized_name=data.get("normalized_name"),
        rfc=data.get("rfc"),
        rfc_type=data.get("rfc_type"),
        website=data.get("website"),
        domain=data.get("domain"),
        industry=data.get("industry"),
        industry_code=data.get("industry_code"),
        employee_count_min=data.get("employee_count_min"),
        employee_count_max=data.get("employee_count_max"),
        employee_count_source=data.get("employee_count_source"),
        phone=data.get("phone"),
        phones=phones,
        email=data.get("email"),
        emails=emails,
        address=address,
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        source_records=source_records,
        source_count=data.get("source_count", len(source_records)),
        data_quality_score=data.get("data_quality_score", 0),
        entity_fingerprint=data.get("entity_fingerprint", ""),
        last_verified_at=data.get("last_verified_at"),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        privacy_classification=data.get("privacy_classification", "B2B_PUBLIC"),
        deletion_status=data.get("deletion_status", "ACTIVE"),
    )
