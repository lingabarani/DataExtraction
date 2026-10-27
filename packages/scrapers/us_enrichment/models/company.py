"""
Canonical US Company data model.
Aggregates data from SEC EDGAR, SAM.gov, USASpending, OpenCorporates, Census CBP.
Output schema mirrors mexico_companies.json exactly, with US-specific identifiers.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from .source_record import SourceProvenanceRecord


@dataclass
class USAddress:
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    state_code: Optional[str] = None
    zip_code: Optional[str] = None
    county: Optional[str] = None
    country: str = "United States"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class USPhoneItem:
    value: str
    source: str
    type: str = "OFFICE"
    verified: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class USEmailItem:
    value: str
    source: str
    verified: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class USCanonicalCompany:
    """
    Canonical Company Entity representing a single US business.
    Aggregates information from SEC EDGAR, SAM.gov, USASpending, OpenCorporates, and Census CBP.
    """
    company_id: str
    legal_name: Optional[str] = None
    trade_name: Optional[str] = None
    normalized_name: Optional[str] = None

    # US Tax/Legal Identifiers (equivalents of Mexico RFC)
    ein: Optional[str] = None                  # Employer Identification Number (primary tax ID)
    entity_type: Optional[str] = None          # CORPORATION, LLC, PARTNERSHIP, NONPROFIT, etc.
    cik: Optional[str] = None                  # SEC CIK number (public companies)
    cage_code: Optional[str] = None            # SAM.gov CAGE code (federal vendors)
    uei: Optional[str] = None                  # SAM.gov Unique Entity ID (replaces DUNS)
    state_of_incorporation: Optional[str] = None  # DE, CA, TX, etc.

    # Web
    website: Optional[str] = None
    domain: Optional[str] = None

    # Industry
    industry: Optional[str] = None
    naics_code: Optional[str] = None           # 6-digit NAICS (equivalent to Mexico SCIAN)
    sic_code: Optional[str] = None             # Legacy SIC (from SEC filings)

    # Size
    employee_count_min: Optional[int] = None
    employee_count_max: Optional[int] = None
    employee_count_source: Optional[str] = None

    # Contact
    phone: Optional[str] = None
    phones: List[USPhoneItem] = field(default_factory=list)
    email: Optional[str] = None
    emails: List[USEmailItem] = field(default_factory=list)

    # Location
    address: USAddress = field(default_factory=USAddress)
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Decision-makers
    decision_makers: List[Any] = field(default_factory=list)

    # Provenance
    source_records: List[SourceProvenanceRecord] = field(default_factory=list)
    source_count: int = 0
    data_quality_score: int = 0
    entity_fingerprint: str = ""
    last_verified_at: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self, include_personal_contacts: bool = True) -> Dict[str, Any]:
        """Convert to output JSON format matching us_companies.json schema."""
        addr = self.address if isinstance(self.address, USAddress) else USAddress(**(self.address or {}))
        return {
            "company_id": self.company_id,
            "legal_name": self.legal_name,
            "trade_name": self.trade_name,
            "normalized_name": self.normalized_name,
            "ein": self.ein,
            "entity_type": self.entity_type,
            "cik": self.cik,
            "cage_code": self.cage_code,
            "uei": self.uei,
            "state_of_incorporation": self.state_of_incorporation,
            "website": self.website,
            "domain": self.domain,
            "industry": self.industry,
            "naics_code": self.naics_code,
            "sic_code": self.sic_code,
            "employee_count_min": self.employee_count_min,
            "employee_count_max": self.employee_count_max,
            "employee_count_source": self.employee_count_source,
            "phone": self.phone,
            "phones": [p.to_dict() if hasattr(p, "to_dict") else p for p in self.phones],
            "email": self.email,
            "emails": [e.to_dict() if hasattr(e, "to_dict") else e for e in self.emails],
            "address": addr.to_dict(),
            "latitude": self.latitude,
            "longitude": self.longitude,
            "source_count": self.source_count,
            "data_quality_score": self.data_quality_score,
            "last_verified_at": self.last_verified_at,
        }

    def to_channel_dict(
        self,
        ingestion_method: str = "api",
        record_index: int = 1,
        validation_flags: Optional[Dict[str, bool]] = None,
        include_personal_contacts: bool = True,
    ) -> Dict[str, Any]:
        """Channel-specific dict output."""
        base = self.to_dict(include_personal_contacts=include_personal_contacts)
        base["_meta"] = {
            "ingestion_method": ingestion_method,
            "record_index": record_index,
            "validation_flags": validation_flags or {},
        }
        return base
