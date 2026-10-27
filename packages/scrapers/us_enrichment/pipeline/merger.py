"""
Multi-source Company Merger for the US B2B Pipeline.
Merges duplicate company records from multiple sources into a single canonical record.
EIN-keyed primary merge, with field-level priority ordering.
"""

from typing import List, Optional
from ..models.company import USCanonicalCompany, USAddress, USPhoneItem, USEmailItem
from ..utils.logging import logger

# Source priority for field merging: SAM.gov > SEC EDGAR > USASpending > OpenCorporates > ProPublica > Census
SOURCE_PRIORITY = {
    "SAM_GOV": 1,
    "SEC_EDGAR": 2,
    "USASPENDING": 3,
    "OPENCORPORATES": 4,
    "PROPUBLICA_990": 5,
    "CENSUS_CBP": 6,
}


class USMergeEngine:
    """
    Merges a cluster of duplicate US company records into a single authoritative record.
    Uses source priority ordering to pick the best value for each field.
    """

    def merge_cluster(self, cluster: List[USCanonicalCompany]) -> USCanonicalCompany:
        """Merge a list of duplicate company records into one canonical record."""
        if len(cluster) == 1:
            c = cluster[0]
            c.source_count = len(c.source_records)
            return c

        # Sort by source priority (highest priority first)
        sorted_cluster = sorted(
            cluster,
            key=lambda c: min(
                SOURCE_PRIORITY.get(r.source, 99)
                for r in c.source_records
            ) if c.source_records else 99
        )

        primary = sorted_cluster[0]

        # Merge all source records and exec candidates
        all_source_records = []
        all_exec_candidates = []
        all_phones: List[USPhoneItem] = []
        all_emails: List[USEmailItem] = []
        seen_sources = set()

        for rec in sorted_cluster:
            for sr in rec.source_records:
                if sr.source not in seen_sources:
                    all_source_records.append(sr)
                    seen_sources.add(sr.source)

            candidates = getattr(rec, "_exec_candidates", [])
            all_exec_candidates.extend(candidates)

            for ph in rec.phones:
                if not any(p.value == ph.value for p in all_phones):
                    all_phones.append(ph)

            for em in rec.emails:
                if not any(e.value == em.value for e in all_emails):
                    all_emails.append(em)

        # Best-value field selection (highest priority source wins, fallback down)
        merged = USCanonicalCompany(
            company_id=primary.company_id,
            legal_name=_best_field([c.legal_name for c in sorted_cluster]),
            trade_name=_best_field([c.trade_name for c in sorted_cluster]),
            normalized_name=_best_field([c.normalized_name for c in sorted_cluster]),
            ein=_best_field([c.ein for c in sorted_cluster]),
            entity_type=_best_field([c.entity_type for c in sorted_cluster]),
            cik=_best_field([c.cik for c in sorted_cluster]),
            cage_code=_best_field([c.cage_code for c in sorted_cluster]),
            uei=_best_field([c.uei for c in sorted_cluster]),
            state_of_incorporation=_best_field([c.state_of_incorporation for c in sorted_cluster]),
            website=_best_field([c.website for c in sorted_cluster]),
            domain=_best_field([c.domain for c in sorted_cluster]),
            industry=_best_field([c.industry for c in sorted_cluster]),
            naics_code=_best_field([c.naics_code for c in sorted_cluster]),
            sic_code=_best_field([c.sic_code for c in sorted_cluster]),
            employee_count_min=_best_int([c.employee_count_min for c in sorted_cluster]),
            employee_count_max=_best_int([c.employee_count_max for c in sorted_cluster]),
            employee_count_source=_best_field([c.employee_count_source for c in sorted_cluster]),
            phone=_best_field([c.phone for c in sorted_cluster]),
            phones=all_phones,
            email=_best_field([c.email for c in sorted_cluster]),
            emails=all_emails,
            address=_merge_address([c.address for c in sorted_cluster]),
            latitude=_best_float([c.latitude for c in sorted_cluster]),
            longitude=_best_float([c.longitude for c in sorted_cluster]),
            source_records=all_source_records,
            source_count=len(all_source_records),
            last_verified_at=primary.last_verified_at,
        )

        # Attach merged exec candidates
        merged._exec_candidates = all_exec_candidates  # type: ignore[attr-defined]

        return merged

    def merge_all(
        self,
        clusters: List[List[USCanonicalCompany]],
    ) -> List[USCanonicalCompany]:
        """Merge all clusters into canonical records."""
        merged = []
        for cluster in clusters:
            try:
                merged.append(self.merge_cluster(cluster))
            except Exception as e:
                logger.error(f"Merge failed for cluster of size {len(cluster)}: {e}")
                if cluster:
                    merged.append(cluster[0])
        return merged


def _best_field(values: list) -> Optional[str]:
    """Returns the first non-null non-empty value in priority order."""
    for v in values:
        if v and str(v).strip():
            return str(v).strip()
    return None


def _best_int(values: list) -> Optional[int]:
    for v in values:
        if v is not None:
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
    return None


def _best_float(values: list) -> Optional[float]:
    for v in values:
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _merge_address(addresses: list) -> USAddress:
    """Merges address fields — picks best non-null value from each field."""
    streets, cities, states, state_codes, zips, counties = [], [], [], [], [], []
    for addr in addresses:
        if not addr:
            continue
        a = addr if isinstance(addr, USAddress) else USAddress(**(addr or {}))
        streets.append(a.street)
        cities.append(a.city)
        states.append(a.state)
        state_codes.append(a.state_code)
        zips.append(a.zip_code)
        counties.append(a.county)

    return USAddress(
        street=_best_field(streets),
        city=_best_field(cities),
        state=_best_field(states),
        state_code=_best_field(state_codes),
        zip_code=_best_field(zips),
        county=_best_field(counties),
        country="United States",
    )


us_merge_engine = USMergeEngine()
