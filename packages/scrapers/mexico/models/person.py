"""
Decision Maker (People / Executive Lead) data model.
Represents individual executives (Founders, C-Suite, VPs, Directors, HR, etc.) associated with companies.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from .source_record import SourceProvenanceRecord


@dataclass
class DecisionMaker:
    """
    Represents an executive / decision-maker at a Mexican B2B company.
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
    seniority_level: str = "C_SUITE"  # FOUNDER, C_SUITE, VP, DIRECTOR, MANAGER, HEAD, LEAD
    department: str = "EXECUTIVE"     # EXECUTIVE, ENGINEERING_IT, FINANCE, SALES_MARKETING, HR_PEOPLE, OPERATIONS, LEGAL_COMPLIANCE, PROCUREMENT
    work_email: Optional[str] = None
    email_pattern: Optional[str] = None
    email_status: str = "UNVERIFIED"  # VERIFIED, PROBABLE, UNVERIFIED, CATCH_ALL, INVALID
    email_confidence_score: int = 0
    mail_provider: str = "UNKNOWN"    # MICROSOFT_365_OUTLOOK, GOOGLE_WORKSPACE, CUSTOM_SMTP, UNKNOWN
    direct_phone: Optional[str] = None
    phone_extension: Optional[str] = None
    phone_type: str = "OFFICE"        # DIRECT, OFFICE, MOBILE
    source_provenance: List[SourceProvenanceRecord] = field(default_factory=list)
    is_active: bool = True
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self, include_personal_contacts: bool = True) -> Dict[str, Any]:
        """Converts model to dictionary matching reference JSON format."""
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
        company_rfc: Optional[str] = None,
        validation_flags: Optional[Dict[str, bool]] = None,
        include_personal_contacts: bool = True,
    ) -> Dict[str, Any]:
        """
        Converts model to exact channel-specific specification JSON
        (output/api/people/api_people.json or output/scraping/people/scraped_people.json).
        """
        prefix = "API-PERS" if ingestion_method == "api" else "SCRP-PERS"
        record_id = f"{prefix}-{record_index:06d}"

        primary_source = self.source_provenance[0].source if self.source_provenance else ("DENUE" if ingestion_method == "api" else "CANACINTRA")
        source_type = "official_api" if ingestion_method == "api" else "public_directory"
        source_record_id = self.source_provenance[0].source_record_id if self.source_provenance else None
        source_url = self.source_provenance[0].source_url if self.source_provenance else None

        val_flags = validation_flags or {
            "email_syntax_valid": bool(self.work_email and "@" in str(self.work_email)),
            "dns_mx_valid": bool(self.company_domain and "." in str(self.company_domain)),
            "phone_valid": bool(self.direct_phone),
        }

        d = {
            "record_id": record_id,
            "data_type": "person",
            "ingestion_method": ingestion_method,
            "source": primary_source,
            "source_type": source_type,
        }

        if ingestion_method == "api":
            d["source_record_id"] = source_record_id
        else:
            d["source_url"] = source_url

        d.update({
            "company_name": self.company_name,
            "company_rfc": company_rfc,
            "full_name": self.full_name,
            "person_name": self.full_name,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "title": self.title or self.standardized_title,
            "job_title": self.title or self.standardized_title,
            "standardized_title": self.standardized_title,
            "seniority": self.seniority_level,
            "seniority_level": self.seniority_level,
            "department": self.department,
            "email": self.work_email if include_personal_contacts else None,
            "phone": self.direct_phone if include_personal_contacts else None,
            "linkedin_url": None,
            "validation": val_flags,
            "quality_score": self.email_confidence_score or 75,
            "collected_at": self.created_at,
            "processed_at": self.updated_at,
        })
        return d

    def to_flat_dict(self, include_personal_contacts: bool = True) -> Dict[str, Any]:
        """Flattened dictionary for CSV and Excel tabular exports."""
        sources_str = ";".join([s.source for s in self.source_provenance])
        return {
            "person_id": self.person_id,
            "full_name": self.full_name,
            "first_name": self.first_name or "",
            "last_name": self.last_name or "",
            "title": self.title,
            "standardized_title": self.standardized_title,
            "seniority_level": self.seniority_level,
            "department": self.department,
            "company_name": self.company_name,
            "company_domain": self.company_domain or "",
            "company_id": self.company_id,
            "work_email": (self.work_email or "") if include_personal_contacts else "",
            "email_status": self.email_status,
            "email_confidence_score": self.email_confidence_score,
            "mail_provider": self.mail_provider,
            "direct_phone": (self.direct_phone or "") if include_personal_contacts else "",
            "phone_extension": (self.phone_extension or "") if include_personal_contacts else "",
            "sources": sources_str,
            "created_at": self.created_at,
        }
