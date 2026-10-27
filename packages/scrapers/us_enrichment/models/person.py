"""
US Decision Maker (People / Executive Lead) data model.
Represents individual executives (Founders, C-Suite, VPs, Directors, HR, etc.) associated with US companies.
Identical schema to Mexico's DecisionMaker for cross-market parity.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from .source_record import SourceProvenanceRecord


@dataclass
class USDecisionMaker:
    """
    Represents an executive / decision-maker at a US B2B company.
    Schema is identical to Mexico's DecisionMaker for cross-market export compatibility.
    """
    person_id: str
    company_id: str
    company_name: str
    company_domain: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: str = ""
    title: str = ""
    standardized_title: str = "EXECUTIVE"
    seniority_level: str = "C_SUITE"   # FOUNDER, C_SUITE, VP, DIRECTOR, MANAGER, HEAD, LEAD
    department: str = "EXECUTIVE"      # EXECUTIVE, ENGINEERING_IT, FINANCE, SALES_MARKETING, HR_PEOPLE, OPERATIONS, LEGAL_COMPLIANCE, PROCUREMENT
    work_email: Optional[str] = None
    email_pattern: Optional[str] = None
    email_status: str = "UNVERIFIED"   # VERIFIED, PROBABLE, UNVERIFIED, CATCH_ALL, INVALID
    email_confidence_score: int = 0
    mail_provider: str = "UNKNOWN"     # MICROSOFT_365_OUTLOOK, GOOGLE_WORKSPACE, CUSTOM_SMTP, UNKNOWN
    direct_phone: Optional[str] = None
    phone_extension: Optional[str] = None
    phone_type: str = "OFFICE"         # DIRECT, OFFICE, MOBILE
    source_provenance: List[SourceProvenanceRecord] = field(default_factory=list)
    is_active: bool = True
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self, include_personal_contacts: bool = True) -> Dict[str, Any]:
        """Converts model to dictionary matching us_people.json format."""
        return {
            "person_id": self.person_id,
            "company_id": self.company_id,
            "company_name": self.company_name,
            "company_domain": self.company_domain,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "title": self.title,
            "standardized_title": self.standardized_title,
            "seniority_level": self.seniority_level,
            "department": self.department,
            "work_email": self.work_email if include_personal_contacts else None,
            "email_status": self.email_status,
            "email_confidence_score": self.email_confidence_score,
            "mail_provider": self.mail_provider,
            "direct_phone": self.direct_phone if include_personal_contacts else None,
            "phone_type": self.phone_type,
            "is_active": self.is_active,
            "created_at": self.created_at,
        }

    def to_channel_dict(
        self,
        ingestion_method: str = "api",
        record_index: int = 1,
        company_ein: Optional[str] = None,
        validation_flags: Optional[Dict[str, bool]] = None,
        include_personal_contacts: bool = True,
    ) -> Dict[str, Any]:
        """Channel-specific dict output."""
        base = self.to_dict(include_personal_contacts=include_personal_contacts)
        base["_meta"] = {
            "ingestion_method": ingestion_method,
            "record_index": record_index,
            "company_ein": company_ein,
            "validation_flags": validation_flags or {},
        }
        return base
