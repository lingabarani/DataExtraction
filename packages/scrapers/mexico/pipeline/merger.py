"""
Source-priority merge engine preserving multi-source provenance.
"""

from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from ..models.company import CanonicalCompany, Address, PhoneItem, EmailItem
from ..models.source_record import SourceProvenanceRecord
from .quality import calculate_data_quality_score
from ..utils.hashing import generate_company_id


# Source authority priority weighting (higher = more authoritative)
SOURCE_PRIORITY: Dict[str, int] = {
    "RPC": 100,
    "SAT": 95,
    "DENUE": 85,
    "SIEM": 80,
    "SUPPLIER_REGISTRY": 75,
    "DATOS_GOB": 70,
    "OTHER": 50,
}


def get_source_priority(source_name: Optional[str]) -> int:
    if not source_name:
        return 0
    return SOURCE_PRIORITY.get(source_name.strip().upper(), 50)


class MergeEngine:
    """
    Combines clusters of duplicate/matching company records into a single authoritative CanonicalCompany.
    """

    def merge_cluster(self, cluster: List[CanonicalCompany]) -> CanonicalCompany:
        """Merges a list of resolving company records into one canonical entity."""
        if not cluster:
            raise ValueError("Cannot merge empty cluster")
        if len(cluster) == 1:
            rec = cluster[0]
            rec.data_quality_score = calculate_data_quality_score(rec)
            rec.source_count = len(rec.source_records)
            return rec

        # Sort cluster records by primary source priority (descending)
        sorted_records = sorted(
            cluster,
            key=lambda c: max([get_source_priority(s.source) for s in c.source_records] or [0]),
            reverse=True,
        )

        primary = sorted_records[0]
        fingerprint = primary.entity_fingerprint
        company_id = generate_company_id(fingerprint)

        # Merge RFC: SAT > SIEM > DENUE > Supplier
        best_rfc = None
        best_rfc_type = None
        for rec in sorted_records:
            if rec.rfc:
                best_rfc = rec.rfc
                best_rfc_type = rec.rfc_type
                break

        # Merge Legal Name: RPC/SAT > SIEM > DENUE
        best_legal_name = None
        for rec in sorted_records:
            if rec.legal_name:
                best_legal_name = rec.legal_name
                break

        # Merge Trade Name: DENUE > SIEM
        best_trade_name = None
        # Prefer DENUE for trade name
        for rec in sorted_records:
            for s in rec.source_records:
                if s.source.upper() == "DENUE" and rec.trade_name:
                    best_trade_name = rec.trade_name
                    break
            if best_trade_name:
                break
        if not best_trade_name:
            for rec in sorted_records:
                if rec.trade_name:
                    best_trade_name = rec.trade_name
                    break

        # Merge Website & Domain
        best_website = None
        best_domain = None
        for rec in sorted_records:
            if rec.website and not best_website:
                best_website = rec.website
                best_domain = rec.domain

        # Merge Industry & SCIAN Code: Prefer DENUE/SIEM
        best_industry = None
        best_industry_code = None
        for rec in sorted_records:
            if rec.industry_code and not best_industry_code:
                best_industry_code = rec.industry_code
                best_industry = rec.industry

        # Merge Employee Count
        emp_min = None
        emp_max = None
        emp_src = None
        for rec in sorted_records:
            if rec.employee_count_min is not None and emp_min is None:
                emp_min = rec.employee_count_min
                emp_max = rec.employee_count_max
                emp_src = rec.employee_count_source

        # Merge Address & Coordinates: Prefer DENUE (authoritative geographic census)
        best_address = Address()
        best_lat = None
        best_lng = None
        for rec in sorted_records:
            addr = rec.address if isinstance(rec.address, Address) else Address(**(rec.address or {}))
            if addr.state and not best_address.state:
                best_address.state = addr.state
            if addr.municipality and not best_address.municipality:
                best_address.municipality = addr.municipality
            if addr.postal_code and not best_address.postal_code:
                best_address.postal_code = addr.postal_code
            if addr.colony and not best_address.colony:
                best_address.colony = addr.colony
            if addr.street and not best_address.street:
                best_address.street = addr.street
                best_address.number = addr.number

            if rec.latitude is not None and best_lat is None:
                best_lat = rec.latitude
                best_lng = rec.longitude

        # Aggregate Phones with Provenance
        all_phones: List[PhoneItem] = []
        seen_phone_vals = set()
        for rec in sorted_records:
            for p in rec.phones:
                if p.value and p.value not in seen_phone_vals:
                    all_phones.append(p)
                    seen_phone_vals.add(p.value)
            if rec.phone and rec.phone not in seen_phone_vals:
                src_name = rec.source_records[0].source if rec.source_records else "UNKNOWN"
                all_phones.append(PhoneItem(value=rec.phone, source=src_name))
                seen_phone_vals.add(rec.phone)

        primary_phone = all_phones[0].value if all_phones else None

        # Aggregate Emails with Provenance
        all_emails: List[EmailItem] = []
        seen_email_vals = set()
        for rec in sorted_records:
            for e in rec.emails:
                if e.value and e.value not in seen_email_vals:
                    all_emails.append(e)
                    seen_email_vals.add(e.value)
            if rec.email and rec.email not in seen_email_vals:
                src_name = rec.source_records[0].source if rec.source_records else "UNKNOWN"
                all_emails.append(EmailItem(value=rec.email, source=src_name))
                seen_email_vals.add(rec.email)

        primary_email = all_emails[0].value if all_emails else None

        # Aggregate Source Provenance Records
        all_source_records: List[SourceProvenanceRecord] = []
        seen_provenance_keys = set()
        for rec in sorted_records:
            for s in rec.source_records:
                pkey = f"{s.source}_{s.source_record_id}"
                if pkey not in seen_provenance_keys:
                    all_source_records.append(s)
                    seen_provenance_keys.add(pkey)

        distinct_sources = {s.source for s in all_source_records}

        merged = CanonicalCompany(
            company_id=company_id,
            legal_name=best_legal_name or primary.legal_name,
            trade_name=best_trade_name or primary.trade_name,
            normalized_name=primary.normalized_name,
            rfc=best_rfc,
            rfc_type=best_rfc_type,
            website=best_website,
            domain=best_domain,
            industry=best_industry,
            industry_code=best_industry_code,
            employee_count_min=emp_min,
            employee_count_max=emp_max,
            employee_count_source=emp_src,
            phone=primary_phone,
            phones=all_phones,
            email=primary_email,
            emails=all_emails,
            address=best_address,
            latitude=best_lat,
            longitude=best_lng,
            source_records=all_source_records,
            source_count=len(distinct_sources),
            data_quality_score=0,
            entity_fingerprint=fingerprint,
            last_verified_at=datetime.now(timezone.utc).isoformat(),
            created_at=min([r.created_at for r in sorted_records if r.created_at] or [datetime.now(timezone.utc).isoformat()]),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        merged.data_quality_score = calculate_data_quality_score(merged)
        return merged

    def merge_all_clusters(self, clusters: List[List[CanonicalCompany]]) -> List[CanonicalCompany]:
        """Merges all deduplication clusters into a list of canonical company records."""
        return [self.merge_cluster(cluster) for cluster in clusters]


merge_engine = MergeEngine()
