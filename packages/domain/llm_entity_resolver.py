"""
DataExtraction — Agent 3: Probabilistic Entity Resolution Semantic Adjudicator
==============================================================================
Evaluates borderline candidate entity matches (0.70 <= Prob < 0.95) from
Splink probabilistic linkage using Ollama LLaMA 3.1:8B.

Capabilities:
  1. Statutory Conflict Pre-filtering: Deterministic rejection on conflicting statutory IDs
     (EIN, RFC, CIK, LEI) before engaging LLM reasoning.
  2. Semantic Adjudication: Disambiguates trade names (DBAs), corporate holding structures,
     subsidiaries, domain variations, and multi-state filings.
  3. Structured Decision Grammar: Enforces typed Pydantic responses:
     - is_same_entity: bool
     - decision: MERGE | SEPARATE | ESCALATE_HUMAN
     - confidence: 0.0 - 1.0
     - reasoning: concise audit explanation
     - score_adjustment: calibrated probability adjustment
  4. Instant Deterministic Fallback: Reverts to token-overlap and domain heuristics
     when LLM is offline, timed out, or circuit breaker is open.
"""

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from packages.infrastructure.config_manager import config_manager
from packages.infrastructure.structured_logger import get_structured_logger

try:
    from packages.infrastructure.ollama_client import (
        CircuitBreakerState,
        ollama_client,
    )
except ImportError:
    from infrastructure.ollama_client import (
        CircuitBreakerState,
        ollama_client,
    )

logger = get_structured_logger("domain.entity_adjudicator")

ADJUDICATION_SYSTEM_PROMPT = """You are the Senior Entity Resolution & Corporate Knowledge Graph Adjudicator for OneExtraction.
Your task is to analyze two candidate business records from a probabilistic record linker and determine whether they represent the exact same legal/operational entity.

Domain Rules:
1. Legal Regimes & Aliases: Companies often operate under DBAs (Doing Business As) or trade names (e.g., "Acme Cloud Services LLC" vs "Acme Technologies DBA Acme Cloud").
2. Multi-State Filings: A corporation incorporated in Delaware often operates a principal executive office in California or New York. Different address states do not preclude a match if name and root domain match.
3. Domains: Matching primary root domains (e.g. acme.com) is strong evidence of identity. Free webmail domains (gmail.com, yahoo.com) provide zero corporate identity signal.
4. Statutory IDs: If both entities have conflicting statutory tax IDs (EIN or RFC), they are strictly separate entities.
5. Decision Policy:
   - "MERGE": Sufficient evidence that both records refer to the same corporate entity.
   - "SEPARATE": Records represent distinct, independent entities (e.g., different companies sharing similar generic words).
   - "ESCALATE_HUMAN": Evidence is ambiguous, contradictory, or insufficient to decide safely.

Output strictly valid JSON with this structure:
{
  "is_same_entity": true or false,
  "decision": "MERGE" | "SEPARATE" | "ESCALATE_HUMAN",
  "confidence": 0.85,
  "reasoning": "Clear explanation of the adjudication decision",
  "score_adjustment": 0.10
}
"""


class AdjudicationResult(BaseModel):
    """Immutable typed adjudication decision for entity resolution auditing."""
    source_id: str
    target_id: str
    is_same_entity: bool
    decision: str = Field(description="MERGE, SEPARATE, or ESCALATE_HUMAN")
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    score_adjustment: float = 0.0
    method: str = "ollama_llama3.1:8b"


def _extract_root_domain(domain: Optional[str]) -> Optional[str]:
    """Extracts lower-cased root domain or returns None."""
    if not domain or not str(domain).strip():
        return None
    d = str(domain).strip().lower().replace("http://", "").replace("https://", "").split("/")[0]
    parts = d.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return d


def _tokenize_name(name: Optional[str]) -> set:
    """Tokenizes company name into alphanumeric word set for token overlap comparisons."""
    if not name:
        return set()
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", " ", str(name).lower())
    stop_words = {"inc", "corp", "corporation", "llc", "llp", "ltd", "limited", "co", "company", "the", "and", "de", "sa", "cv"}
    return {w for w in cleaned.split() if len(w) > 1 and w not in stop_words}


class LLMEntityResolver:
    """
    Semantic adjudication service for borderline entity matches.
    Combines deterministic statutory guards with LLaMA 3.1:8B reasoning and heuristic failover.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or config_manager.get_agent_ai_config()
        self.enabled = bool(cfg.get("entity_adjudication_enabled", True))
        self.timeout = float(cfg.get("entity_adjudication_timeout", 10.0))
        self.concurrency = int(cfg.get("batch_concurrency", 5))

    def check_statutory_precedence(
        self, record_a: Dict[str, Any], record_b: Dict[str, Any]
    ) -> Optional[Tuple[bool, str, str]]:
        """
        Evaluates definitive statutory tax IDs (EIN, RFC, CIK, LEI).
        Returns:
            Tuple of (is_same_entity, decision, reasoning) if deterministically resolved, else None.
        """
        tax_a = record_a.get("statutory_tax_id") or record_a.get("ein") or record_a.get("rfc")
        tax_b = record_b.get("statutory_tax_id") or record_b.get("ein") or record_b.get("rfc")

        if tax_a and tax_b:
            clean_a = re.sub(r"[^A-Za-z0-9]", "", str(tax_a)).upper()
            clean_b = re.sub(r"[^A-Za-z0-9]", "", str(tax_b)).upper()
            if clean_a and clean_b:
                if clean_a == clean_b:
                    return (
                        True,
                        "MERGE",
                        f"Deterministic identity: matching statutory tax ID ({clean_a})",
                    )
                else:
                    return (
                        False,
                        "SEPARATE",
                        f"Deterministic conflict: distinct statutory tax IDs ({clean_a} vs {clean_b})",
                    )
        return None

    def heuristic_adjudicate(
        self,
        record_a: Dict[str, Any],
        record_b: Dict[str, Any],
        prior_prob: float = 0.85,
    ) -> AdjudicationResult:
        """
        Deterministic fallback when Ollama is offline, times out, or circuit breaker is open.
        Uses Jaccard token overlap of legal names and registered domain matching.
        """
        id_a = str(record_a.get("id") or record_a.get("org_id") or record_a.get("unique_id") or "left")
        id_b = str(record_b.get("id") or record_b.get("org_id") or record_b.get("unique_id") or "right")

        # Statutory check first
        stat = self.check_statutory_precedence(record_a, record_b)
        if stat:
            same, dec, reason = stat
            return AdjudicationResult(
                source_id=id_a,
                target_id=id_b,
                is_same_entity=same,
                decision=dec,
                confidence=1.0,
                reasoning=reason + " (Deterministic Rule)",
                score_adjustment=0.15 if same else -0.50,
                method="deterministic_fallback",
            )

        dom_a = _extract_root_domain(record_a.get("domain") or record_a.get("website"))
        dom_b = _extract_root_domain(record_b.get("domain") or record_b.get("website"))
        domains_match = bool(dom_a and dom_b and dom_a == dom_b)

        tokens_a = _tokenize_name(record_a.get("name") or record_a.get("legal_name"))
        tokens_b = _tokenize_name(record_b.get("name") or record_b.get("legal_name"))
        union = tokens_a | tokens_b
        jaccard = (len(tokens_a & tokens_b) / len(union)) if union else 0.0

        st_a = str(record_a.get("state_code") or record_a.get("state") or "").strip().upper()[:2]
        st_b = str(record_b.get("state_code") or record_b.get("state") or "").strip().upper()[:2]
        states_match = bool(st_a and st_b and st_a == st_b)

        # Rule evaluation
        if domains_match and jaccard >= 0.50:
            return AdjudicationResult(
                source_id=id_a,
                target_id=id_b,
                is_same_entity=True,
                decision="MERGE",
                confidence=round(0.85 + (jaccard * 0.1), 2),
                reasoning=f"Matching root domain ({dom_a}) and strong name token overlap ({jaccard:.2f})",
                score_adjustment=0.10,
                method="deterministic_fallback",
            )
        elif jaccard >= 0.85 and states_match:
            return AdjudicationResult(
                source_id=id_a,
                target_id=id_b,
                is_same_entity=True,
                decision="MERGE",
                confidence=0.88,
                reasoning=f"High name token similarity ({jaccard:.2f}) within same jurisdiction ({st_a})",
                score_adjustment=0.10,
                method="deterministic_fallback",
            )
        elif jaccard < 0.25 and not domains_match:
            return AdjudicationResult(
                source_id=id_a,
                target_id=id_b,
                is_same_entity=False,
                decision="SEPARATE",
                confidence=0.80,
                reasoning=f"Low name token overlap ({jaccard:.2f}) with distinct or missing domains",
                score_adjustment=-0.25,
                method="deterministic_fallback",
            )
        else:
            return AdjudicationResult(
                source_id=id_a,
                target_id=id_b,
                is_same_entity=False,
                decision="ESCALATE_HUMAN",
                confidence=0.50,
                reasoning=f"Borderline ambiguity (prior={prior_prob:.2f}, token_sim={jaccard:.2f}); routing to review queue",
                score_adjustment=0.0,
                method="deterministic_fallback",
            )

    async def adjudicate_pair(
        self,
        record_a: Dict[str, Any],
        record_b: Dict[str, Any],
        prior_prob: float = 0.85,
    ) -> AdjudicationResult:
        """
        Adjudicates a candidate pair using LLaMA 3.1:8B with deterministic pre-checks and fallback.
        """
        id_a = str(record_a.get("id") or record_a.get("org_id") or record_a.get("unique_id") or "left")
        id_b = str(record_b.get("id") or record_b.get("org_id") or record_b.get("unique_id") or "right")

        # 1. Deterministic statutory pre-checks (zero latency)
        stat = self.check_statutory_precedence(record_a, record_b)
        if stat:
            same, dec, reason = stat
            return AdjudicationResult(
                source_id=id_a,
                target_id=id_b,
                is_same_entity=same,
                decision=dec,
                confidence=1.0,
                reasoning=reason,
                score_adjustment=0.15 if same else -0.50,
                method="statutory_rule",
            )

        # 2. Invoke Ollama LLaMA 3.1:8B if available
        if self.enabled and ollama_client.is_available():
            prompt = f"""Compare these two business records and adjudicate whether they are the same entity:

Record 1:
- Name: {record_a.get('name') or record_a.get('company_name')}
- Legal Name: {record_a.get('legal_name')}
- Domain / Website: {record_a.get('domain') or record_a.get('website')}
- Jurisdiction / State: {record_a.get('state_code') or record_a.get('state')}
- Address: {record_a.get('street_address') or record_a.get('address')}
- Industry: {record_a.get('industry')}
- Tax ID / EIN: {record_a.get('statutory_tax_id') or record_a.get('ein')}

Record 2:
- Name: {record_b.get('name') or record_b.get('company_name')}
- Legal Name: {record_b.get('legal_name')}
- Domain / Website: {record_b.get('domain') or record_b.get('website')}
- Jurisdiction / State: {record_b.get('state_code') or record_b.get('state')}
- Address: {record_b.get('street_address') or record_b.get('address')}
- Industry: {record_b.get('industry')}
- Tax ID / EIN: {record_b.get('statutory_tax_id') or record_b.get('ein')}

Prior Linker Match Probability: {prior_prob:.2f}
"""
            try:
                llm_json = await ollama_client.generate_structured(
                    prompt=prompt,
                    system=ADJUDICATION_SYSTEM_PROMPT,
                    timeout=self.timeout,
                )
                if isinstance(llm_json, dict) and "decision" in llm_json:
                    dec = str(llm_json.get("decision")).upper().strip()
                    if dec not in ("MERGE", "SEPARATE", "ESCALATE_HUMAN"):
                        dec = "MERGE" if llm_json.get("is_same_entity") else "SEPARATE"

                    conf = float(llm_json.get("confidence", 0.85))
                    conf = max(0.0, min(1.0, conf))
                    score_adj = float(llm_json.get("score_adjustment", 0.05 if dec == "MERGE" else -0.15))
                    score_adj = max(-0.5, min(0.3, score_adj))

                    return AdjudicationResult(
                        source_id=id_a,
                        target_id=id_b,
                        is_same_entity=bool(llm_json.get("is_same_entity", dec == "MERGE")),
                        decision=dec,
                        confidence=conf,
                        reasoning=str(llm_json.get("reasoning", "Semantic analysis performed by LLaMA 3.1:8B")),
                        score_adjustment=score_adj,
                        method="ollama_llama3.1:8b",
                    )
            except Exception as exc:
                logger.warning("LLM entity adjudication failed, utilizing heuristic fallback: %s", exc)

        # 3. Fallback to heuristic rules
        return self.heuristic_adjudicate(record_a, record_b, prior_prob=prior_prob)

    async def adjudicate_batch(
        self,
        pairs: List[Tuple[Dict[str, Any], Dict[str, Any], float]],
    ) -> List[AdjudicationResult]:
        """
        Adjudicates a batch of candidate pairs concurrently with bounded worker concurrency.
        """
        if not pairs:
            return []

        sem = asyncio.Semaphore(self.concurrency)

        async def _bound_adjudicate(a, b, p):
            async with sem:
                return await self.adjudicate_pair(a, b, prior_prob=p)

        tasks = [_bound_adjudicate(a, b, p) for (a, b, p) in pairs]
        return await asyncio.gather(*tasks)


# Global singleton instance
llm_entity_resolver = LLMEntityResolver()

__all__ = ["LLMEntityResolver", "AdjudicationResult", "llm_entity_resolver"]

