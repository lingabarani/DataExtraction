"""
Deduplication engine utilizing deterministic entity fingerprinting and high-speed block resolution clustering.
"""

from collections import defaultdict
from typing import List, Dict, Tuple, Set
from ..models.company import CanonicalCompany
from ..utils.hashing import generate_entity_fingerprint
from .entity_resolution import entity_resolver, MatchResult
from ..utils.logging import logger


class DeduplicationEngine:
    """
    Identifies duplicate records within and across sources, grouping them into merge clusters.
    """

    def __init__(self):
        self.resolver = entity_resolver

    def deduplicate(
        self,
        records: List[CanonicalCompany]
    ) -> Tuple[List[List[CanonicalCompany]], List[CanonicalCompany], int]:
        """
        Groups records into clusters of identical/resolving entities using fast multi-key blocking.
        
        Returns:
            (merge_clusters, review_queue, duplicate_count)
        """
        # Step 1: Deterministic Fingerprint Grouping (Fast O(N) pass)
        fingerprint_groups: Dict[str, List[CanonicalCompany]] = defaultdict(list)
        for rec in records:
            addr = rec.address
            fp = generate_entity_fingerprint(
                rfc=rec.rfc,
                normalized_name=rec.normalized_name,
                state=addr.state if addr else None,
                municipality=addr.municipality if addr else None,
                domain=rec.domain,
            )
            rec.entity_fingerprint = fp
            fingerprint_groups[fp].append(rec)

        merge_clusters: List[List[CanonicalCompany]] = []
        review_queue: List[CanonicalCompany] = []
        duplicate_count = 0

        # Step 2: Form initial clusters from exact fingerprints
        unclustered: List[CanonicalCompany] = []
        for fp, group in fingerprint_groups.items():
            if len(group) > 1:
                duplicate_count += len(group) - 1
                merge_clusters.append(group)
            else:
                unclustered.append(group[0])

        # Step 3: High-speed multi-token blocking for unclustered records
        # Block by (State, First Two Name Tokens) to avoid O(N^2) state-wide scans
        blocks: Dict[str, List[CanonicalCompany]] = defaultdict(list)
        for rec in unclustered:
            state_key = (rec.address.state if rec.address and rec.address.state else "UNKNOWN").lower().strip()
            name_tokens = (rec.normalized_name or "").split()
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

                    match_res = self.resolver.match(c1, c2)
                    if match_res.decision == "AUTO_MERGE":
                        cluster.append(c2)
                        visited.add(c2.company_id)
                        duplicate_count += 1
                    elif match_res.decision == "REVIEW_QUEUE":
                        review_queue.append(c2)

                if len(cluster) > 1:
                    merge_clusters.append(cluster)
                else:
                    merge_clusters.append([c1])

        logger.info(
            "Deduplication completed",
            total_input=len(records),
            unique_clusters=len(merge_clusters),
            duplicates_found=duplicate_count,
            review_queue=len(review_queue),
        )

        return merge_clusters, review_queue, duplicate_count


deduplication_engine = DeduplicationEngine()
