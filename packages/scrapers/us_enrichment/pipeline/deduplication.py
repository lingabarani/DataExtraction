"""
Deduplication engine for US B2B pipeline.
Uses EIN-based deterministic fingerprinting as primary dedup key (equivalent to Mexico's RFC).
Falls back to company name + state fuzzy matching for records without EIN.
"""

import hashlib
import uuid
from collections import defaultdict
from typing import List, Dict, Tuple, Set, Optional
from ..models.company import USCanonicalCompany
from ..utils.logging import logger


def generate_us_company_id(
    ein: Optional[str] = None,
    legal_name: Optional[str] = None,
    state: Optional[str] = None,
    cik: Optional[str] = None,
) -> str:
    """
    Generates a deterministic UUIDv5-based company ID.
    Primary key: EIN (equivalent to Mexico's RFC)
    Fallback: CIK → normalized_name + state
    Format: us_<uuid5-hex-formatted>
    """
    if ein:
        # Strip formatting: "12-3456789" -> "123456789"
        clean_ein = ein.replace("-", "").strip()
        if len(clean_ein) >= 8:
            fp_str = f"EIN:{clean_ein}"
            uid = uuid.uuid5(uuid.NAMESPACE_DNS, fp_str)
            h = uid.hex
            return f"us_{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"

    if cik:
        fp_str = f"CIK:{cik.strip().zfill(10)}"
        uid = uuid.uuid5(uuid.NAMESPACE_DNS, fp_str)
        h = uid.hex
        return f"us_{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"

    # Fallback: name + state fingerprint
    name_clean = _normalize_for_fp(legal_name or "")
    state_clean = (state or "").upper().strip()
    fp_str = f"NAME:{name_clean}::STATE:{state_clean}"
    uid = uuid.uuid5(uuid.NAMESPACE_DNS, fp_str)
    h = uid.hex
    return f"us_{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def _normalize_for_fp(name: str) -> str:
    """Normalize company name for fingerprinting — removes suffixes, punctuation."""
    n = name.upper().strip()
    for s in [" LLC", " INC", " CORP", " LTD", " LP", " LLP", " PC",
              " PLLC", " CO", " COMPANY", " INCORPORATED", " LIMITED",
              " CORPORATION", " GROUP", " HOLDINGS", " SERVICES",
              " SOLUTIONS", " TECHNOLOGIES", " TECHNOLOGIES INC"]:
        if n.endswith(s):
            n = n[:-len(s)].strip()
    # Remove punctuation
    n = "".join(c for c in n if c.isalnum() or c == " ")
    return " ".join(n.split())


class USDeduplicationEngine:
    """
    Groups US company records into merge clusters using EIN-first deduplication.
    EIN matching = exact (deterministic), same as Mexico's RFC-based approach.
    """

    def deduplicate(
        self,
        records: List[USCanonicalCompany],
    ) -> Tuple[List[List[USCanonicalCompany]], List[USCanonicalCompany], int]:
        """
        Groups records into merge clusters.
        Returns: (merge_clusters, review_queue, duplicate_count)
        """
        # Step 1: EIN-based exact grouping (primary key)
        ein_groups: Dict[str, List[USCanonicalCompany]] = defaultdict(list)
        no_ein_records: List[USCanonicalCompany] = []

        for rec in records:
            if rec.ein:
                clean_ein = rec.ein.replace("-", "").strip()
                ein_groups[clean_ein].append(rec)
            else:
                no_ein_records.append(rec)

        merge_clusters: List[List[USCanonicalCompany]] = []
        review_queue: List[USCanonicalCompany] = []
        duplicate_count = 0

        # Form clusters from EIN groups
        for ein, group in ein_groups.items():
            if len(group) > 1:
                duplicate_count += len(group) - 1
            merge_clusters.append(group)

        # Step 2: CIK-based grouping for non-EIN records
        cik_groups: Dict[str, List[USCanonicalCompany]] = defaultdict(list)
        remaining: List[USCanonicalCompany] = []

        for rec in no_ein_records:
            if rec.cik:
                cik_groups[rec.cik.strip().zfill(10)].append(rec)
            else:
                remaining.append(rec)

        for cik, group in cik_groups.items():
            if len(group) > 1:
                duplicate_count += len(group) - 1
            merge_clusters.append(group)

        # Step 3: Name+State blocking for remaining records (same as Mexico's approach)
        blocks: Dict[str, List[USCanonicalCompany]] = defaultdict(list)
        for rec in remaining:
            state_key = (rec.address.state_code or rec.address.state or "UNKNOWN").upper()
            name_tokens = _normalize_for_fp(rec.normalized_name or rec.legal_name or "").split()
            token_prefix = "_".join(name_tokens[:2]) if len(name_tokens) >= 2 else (name_tokens[0] if name_tokens else "NO_NAME")
            block_key = f"{state_key}::{token_prefix}"
            blocks[block_key].append(rec)

        visited: Set[str] = set()
        for block_key, block_records in blocks.items():
            n = len(block_records)
            for i in range(n):
                c1 = block_records[i]
                if c1.company_id in visited:
                    continue
                cluster = [c1]
                visited.add(c1.company_id)
                for j in range(i + 1, n):
                    c2 = block_records[j]
                    if c2.company_id in visited:
                        continue
                    if _fuzzy_match(c1, c2):
                        cluster.append(c2)
                        visited.add(c2.company_id)
                        duplicate_count += 1
                merge_clusters.append(cluster)

        logger.info(
            "US Deduplication completed",
            total_input=len(records),
            unique_clusters=len(merge_clusters),
            duplicates_found=duplicate_count,
            review_queue=len(review_queue),
        )

        return merge_clusters, review_queue, duplicate_count


def _fuzzy_match(c1: USCanonicalCompany, c2: USCanonicalCompany) -> bool:
    """
    Returns True if two records should be merged based on name similarity + state.
    Uses Jaccard token similarity threshold of 0.85.
    """
    n1 = set(_normalize_for_fp(c1.normalized_name or c1.legal_name or "").split())
    n2 = set(_normalize_for_fp(c2.normalized_name or c2.legal_name or "").split())
    if not n1 or not n2:
        return False
    intersection = len(n1 & n2)
    union = len(n1 | n2)
    jaccard = intersection / union if union else 0
    if jaccard < 0.85:
        return False
    # Also require same state
    s1 = (c1.address.state_code or c1.address.state or "").upper()
    s2 = (c2.address.state_code or c2.address.state or "").upper()
    return s1 == s2 or not s1 or not s2


us_deduplication_engine = USDeduplicationEngine()
