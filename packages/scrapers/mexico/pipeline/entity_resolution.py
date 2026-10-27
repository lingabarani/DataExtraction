"""
Entity Resolution Engine for Mexican company records across multiple sources.
Implements a 6-stage progressive matching pipeline with confidence scoring.
"""

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional, List, Tuple
from ..models.company import CanonicalCompany, Address
from ..utils.rfc_utils import is_valid_rfc, is_generic_rfc


@dataclass
class MatchResult:
    score: float
    reasons: List[str] = field(default_factory=list)
    decision: str = "SEPARATE_ENTITIES"  # 'AUTO_MERGE', 'REVIEW_QUEUE', 'SEPARATE_ENTITIES'


def string_similarity(s1: Optional[str], s2: Optional[str]) -> float:
    """Calculates Levenshtein-like similarity ratio (0.0 to 1.0) between two strings."""
    if not s1 or not s2:
        return 0.0
    return SequenceMatcher(None, s1.strip().upper(), s2.strip().upper()).ratio()


class EntityResolver:
    """
    Multi-stage entity matching and resolution engine.
    """

    def __init__(self, auto_merge_threshold: float = 0.95, review_threshold: float = 0.80):
        self.auto_merge_threshold = auto_merge_threshold
        self.review_threshold = review_threshold

    def match(self, c1: CanonicalCompany, c2: CanonicalCompany) -> MatchResult:
        """
        Compares two company records across 6 progressive matching stages.
        """
        reasons: List[str] = []
        highest_score: float = 0.0

        # Stage 1: Exact RFC Match (Highest Confidence)
        if c1.rfc and c2.rfc:
            if is_valid_rfc(c1.rfc) and is_valid_rfc(c2.rfc) and not (is_generic_rfc(c1.rfc) or is_generic_rfc(c2.rfc)):
                if c1.rfc.strip().upper() == c2.rfc.strip().upper():
                    reasons.append("EXACT_RFC_MATCH")
                    return MatchResult(score=1.0, reasons=reasons, decision="AUTO_MERGE")

        # Stage 2: Exact Source Record ID Match
        if c1.source_records and c2.source_records:
            for s1 in c1.source_records:
                for s2 in c2.source_records:
                    if s1.source == s2.source and s1.source_record_id and s2.source_record_id:
                        if s1.source_record_id == s2.source_record_id:
                            reasons.append("EXACT_SOURCE_RECORD_ID_MATCH")
                            return MatchResult(score=1.0, reasons=reasons, decision="AUTO_MERGE")

        addr1 = c1.address if isinstance(c1.address, Address) else Address(**(c1.address or {}))
        addr2 = c2.address if isinstance(c2.address, Address) else Address(**(c2.address or {}))

        same_state = bool(addr1.state and addr2.state and addr1.state.strip().lower() == addr2.state.strip().lower())
        same_muni = bool(
            addr1.municipality and addr2.municipality and addr1.municipality.strip().lower() == addr2.municipality.strip().lower()
        )
        same_cp = bool(addr1.postal_code and addr2.postal_code and addr1.postal_code == addr2.postal_code)

        # Stage 3: Exact Normalized Domain + Same State
        if c1.domain and c2.domain:
            if c1.domain.strip().lower() == c2.domain.strip().lower():
                reasons.append("EXACT_DOMAIN_MATCH")
                if same_state or not addr1.state or not addr2.state:
                    highest_score = max(highest_score, 0.96)
                    reasons.append("MATCHING_STATE_OR_NATIONWIDE")
                else:
                    highest_score = max(highest_score, 0.85)

        # Stage 4 & 5: Normalized Legal / Trade Name Comparison
        name1 = c1.normalized_name or (c1.legal_name or c1.trade_name or "").strip().upper()
        name2 = c2.normalized_name or (c2.legal_name or c2.trade_name or "").strip().upper()

        if name1 and name2:
            if name1 == name2:
                reasons.append("EXACT_NORMALIZED_NAME_MATCH")
                if same_state and same_muni:
                    highest_score = max(highest_score, 0.95)
                    reasons.append("MATCHING_MUNICIPALITY_AND_STATE")
                elif same_state or same_cp:
                    highest_score = max(highest_score, 0.90)
                    reasons.append("MATCHING_STATE_OR_CP")
                else:
                    highest_score = max(highest_score, 0.75)
            else:
                # Stage 6: Fuzzy Name Matching
                sim = string_similarity(name1, name2)
                if sim >= 0.88:
                    reasons.append(f"FUZZY_NAME_MATCH_RATIO_{sim:.2f}")
                    if same_state and (same_muni or same_cp):
                        highest_score = max(highest_score, 0.88)
                        reasons.append("FUZZY_MATCHING_LOCATION")
                    elif same_state:
                        highest_score = max(highest_score, 0.82)
                    else:
                        highest_score = max(highest_score, 0.65)

        # Decision based on configurable thresholds
        if highest_score >= self.auto_merge_threshold:
            decision = "AUTO_MERGE"
        elif highest_score >= self.review_threshold:
            decision = "REVIEW_QUEUE"
        else:
            decision = "SEPARATE_ENTITIES"

        return MatchResult(score=highest_score, reasons=reasons, decision=decision)


entity_resolver = EntityResolver()
