"""
Canonical company data model and associated nested structures.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from .source_record import SourceProvenanceRecord
from .person import DecisionMaker


@dataclass
class Address:
    street: Optional[str] = None
    number: Optional[str] = None
    colony: Optional[str] = None
    municipality: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: str = "Mexico"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PhoneItem:
    value: str
    source: str
    type: str = "OFFICE"
    verified: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EmailItem:
    value: str
    source: str
    verified: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CanonicalCompany:
    """
    Canonical Company Entity representing a single business in Mexico.
    Aggregates information from DENUE, SIEM, supplier registries, and official portals.
    """
    company_id: str
    legal_name: Optional[str] = None
    trade_name: Optional[str] = None
    normalized_name: Optional[str] = None
    rfc: Optional[str] = None
    rfc_type: Optional[str] = None
    website: Optional[str] = None
    domain: Optional[str] = None
    industry: Optional[str] = None
    industry_code: Optional[str] = None
    employee_count_min: Optional[int] = None
    employee_count_max: Optional[int] = None
    employee_count_source: Optional[str] = None
    phone: Optional[str] = None
    phones: List[PhoneItem] = field(default_factory=list)
    email: Optional[str] = None
    emails: List[EmailItem] = field(default_factory=list)
    address: Address = field(default_factory=Address)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    decision_makers: List[DecisionMaker] = field(default_factory=list)
    source_records: List[SourceProvenanceRecord] = field(default_factory=list)
    source_count: int = 0
    data_quality_score: int = 0
    entity_fingerprint: str = ""
    last_verified_at: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    privacy_classification: str = "B2B_PUBLIC"
    deletion_status: str = "ACTIVE"

    def to_dict(self, include_personal_contacts: bool = True) -> Dict[str, Any]:
        """Converts model to dictionary matching reference JSON format."""
        d = {
            "company_id": self.company_id,
            "legal_name": self.legal_name,
            "trade_name": self.trade_name,
            "normalized_name": self.normalized_name,
            "rfc": self.rfc,
            "rfc_type": self.rfc_type,
            "website": self.website,
            "domain": self.domain,
            "industry": self.industry,
            "industry_code": self.industry_code,
            "employee_count_min": self.employee_count_min,
            "employee_count_max": self.employee_count_max,
            "employee_count_source": self.employee_count_source,
            "phone": self.phone if include_personal_contacts else None,
            "phones": [p.to_dict() for p in self.phones] if include_personal_contacts else [],
            "email": self.email if include_personal_contacts else None,
            "emails": [e.to_dict() for e in self.emails] if include_personal_contacts else [],
            "address": self.address.to_dict() if isinstance(self.address, Address) else self.address,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "source_count": self.source_count or len(self.source_records),
            "data_quality_score": self.data_quality_score,
            "last_verified_at": self.last_verified_at or self.created_at,
        }
        return d

    def to_channel_dict(
        self,
        ingestion_method: str = "api",
        record_index: int = 1,
        validation_flags: Optional[Dict[str, bool]] = None,
        include_personal_contacts: bool = True,
    ) -> Dict[str, Any]:
        """
        Converts model to exact channel-specific specification JSON
        (output/api/companies/api_companies.json or output/scraping/companies/scraped_companies.json).
        """
        prefix = "API-COMP" if ingestion_method == "api" else "SCRP-COMP"
        record_id = f"{prefix}-{record_index:06d}"
        
        primary_source = self.source_records[0].source if self.source_records else ("DENUE" if ingestion_method == "api" else "CANACINTRA")
        source_type = "official_api" if ingestion_method == "api" else "public_directory"
        source_record_id = self.source_records[0].source_record_id if self.source_records else None
        source_url = self.source_records[0].source_url if self.source_records else (self.website or None)

        addr_dict = self.address.to_dict() if isinstance(self.address, Address) else (self.address or {})
        
        # Build employee range string if available
        emp_range = None
        if self.employee_count_min is not None and self.employee_count_max is not None:
            emp_range = f"{self.employee_count_min}-{self.employee_count_max}"
        elif self.employee_count_min is not None:
            emp_range = f"{self.employee_count_min}+"
        elif self.employee_count_source:
            emp_range = str(self.employee_count_source)

        val_flags = validation_flags or {
            "name_valid": bool(self.legal_name or self.trade_name),
            "rfc_valid": bool(self.rfc),
            "phone_valid": bool(self.phone),
            "postal_code_valid": bool(addr_dict.get("postal_code")),
            "domain_valid": bool(self.domain and "." in str(self.domain)),
            "email_syntax_valid": bool(self.email and "@" in str(self.email)),
            "dns_mx_valid": bool(self.domain and "." in str(self.domain)),
        }

        d = {
            "record_id": record_id,
            "data_type": "company",
            "ingestion_method": ingestion_method,
            "source": primary_source,
            "source_type": source_type,
            "source_record_id": source_record_id,
            "legal_name": self.legal_name,
            "trade_name": self.trade_name,
            "rfc": self.rfc,
            "industry": self.industry,
        }

        if ingestion_method == "api":
            d["scian_code"] = self.industry_code
            d["employee_range"] = emp_range
        else:
            d["source_url"] = source_url

        d.update({
            "website": self.website,
            "domain": self.domain,
            "phone": self.phone if include_personal_contacts else None,
            "email": self.email if include_personal_contacts else None,
            "address": {
                "street": addr_dict.get("street"),
                "municipality": addr_dict.get("municipality"),
                "state": addr_dict.get("state"),
                "postal_code": addr_dict.get("postal_code"),
                "country": addr_dict.get("country", "Mexico"),
            },
            "latitude": self.latitude,
            "longitude": self.longitude,
            "validation": val_flags,
            "quality_score": self.data_quality_score,
            "collected_at": self.created_at,
            "processed_at": self.updated_at,
        })
        return d

    def to_flat_dict(self, include_personal_contacts: bool = True) -> Dict[str, Any]:
        """Flattened dictionary for CSV and Excel tabular export."""
        addr = self.address if isinstance(self.address, Address) else Address(**(self.address or {}))
        sources_str = ";".join([s.source for s in self.source_records])
        return {
            "company_id": self.company_id,
            "legal_name": self.legal_name or "",
            "trade_name": self.trade_name or "",
            "rfc": self.rfc or "",
            "rfc_type": self.rfc_type or "",
            "website": self.website or "",
            "domain": self.domain or "",
            "industry": self.industry or "",
            "industry_code": self.industry_code or "",
            "employee_count_min": self.employee_count_min if self.employee_count_min is not None else "",
            "employee_count_max": self.employee_count_max if self.employee_count_max is not None else "",
            "employee_count_source": self.employee_count_source or "",
            "phone": (self.phone or "") if include_personal_contacts else "",
            "email": (self.email or "") if include_personal_contacts else "",
            "street": addr.street or "",
            "number": addr.number or "",
            "colony": addr.colony or "",
            "municipality": addr.municipality or "",
            "state": addr.state or "",
            "postal_code": addr.postal_code or "",
            "country": addr.country or "Mexico",
            "latitude": self.latitude if self.latitude is not None else "",
            "longitude": self.longitude if self.longitude is not None else "",
            "source_count": self.source_count or len(self.source_records),
            "sources": sources_str,
            "data_quality_score": self.data_quality_score,
            "last_verified_at": self.last_verified_at or "",
            "created_at": self.created_at or "",
        }
