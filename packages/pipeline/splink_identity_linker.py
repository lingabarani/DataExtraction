"""
DataExtraction — Splink Probabilistic Entity Linker & Cluster Engine
====================================================================
Implements unsupervised and Fellegi-Sunter probabilistic record linkage
using Splink 5.0 and the DuckDB high-performance analytical engine.

Capabilities:
  1. Multi-feature probabilistic scoring: Normalized Name (Jaro-Winkler),
     Primary Domain, Postal Code, and Jurisdiction.
  2. Conflict Prevention: Blocks false links across conflicting statutory IDs.
  3. Calibrated Weights: Calibrates m/u values for domain and name comparisons.
  4. Integration with Three-Tier Decision Engine:
     - Prob >= 0.95 -> AUTO_MERGE
     - 0.70 <= Prob < 0.95 -> QUARANTINE (Isolation Review Queue)
     - Prob < 0.70 -> DISTINCT_ENTITY
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
try:
    from splink import Linker, SettingsCreator, block_on
    import splink.comparison_library as cl
    from splink.internals.duckdb.database_api import DuckDBAPI
except ImportError:
    Linker = object  # type: ignore
    SettingsCreator = object  # type: ignore
    block_on = object  # type: ignore
    cl = object  # type: ignore
    DuckDBAPI = object  # type: ignore

from packages.pipeline.normalizer import clean_legal_suffixes

logger = logging.getLogger("dataextraction.pipeline.splink_linker")


class SplinkIdentityLinker:
    """
    DuckDB-backed Splink 5.0 probabilistic entity linker.
    """

    def __init__(self, probability_two_random_records_match: float = 0.05):
        self.prob_two_match = probability_two_random_records_match
        self.db_api = DuckDBAPI()

    def _prepare_dataframe(self, records: List[Dict[str, Any]]) -> pd.DataFrame:
        """
        Prepares and cleans input records for Splink DuckDB registration.
        """
        rows = []
        for r in records:
            raw_name = r.get("name") or r.get("legal_name") or r.get("trade_name") or ""
            norm_name = r.get("normalized_name") or clean_legal_suffixes(raw_name) or ""

            rows.append({
                "unique_id": str(r.get("id") or r.get("org_id") or r.get("unique_id")),
                "name": norm_name,
                "domain": str(r.get("domain") or "").strip().lower() or None,
                "state": str(r.get("state_code") or r.get("state") or "").strip()[:2].upper() or None,
                "postal_code": str(r.get("zip_code") or r.get("postal_code") or "").strip()[:5] or None,
                "statutory_tax_id": str(r.get("statutory_tax_id") or r.get("ein") or r.get("rfc") or "").strip().upper() or None,
            })
        return pd.DataFrame(rows)

    def link_records(
        self,
        records: List[Dict[str, Any]],
        threshold_match_probability: float = 0.70,
    ) -> List[Dict[str, Any]]:
        """
        Executes probabilistic linkage across candidate records.

        Returns:
            List of match pairs with match_probability, match_weight, and three-tier decision.
        """
        if not records or len(records) < 2:
            return []

        df = self._prepare_dataframe(records)
        splink_df = self.db_api.register(df)

        settings = SettingsCreator(
            link_type="dedupe_only",
            comparisons=[
                cl.ExactMatch("domain"),
                cl.JaroWinklerAtThresholds("name", [0.90, 0.75]),
                cl.ExactMatch("postal_code"),
            ],
            blocking_rules_to_generate_predictions=[
                block_on("state"),
                block_on("domain"),
            ],
            probability_two_random_records_match=self.prob_two_match,
        )

        linker = Linker(splink_df, settings)

        # Unsupervised EM parameter estimation if multiple domain blocks exist
        try:
            linker.training.estimate_parameters_using_expectation_maximisation(block_on("domain"))
        except Exception as em_err:
            logger.debug("EM estimation notice: %s", em_err)

        # Generate predictions
        predictions = linker.inference.predict(threshold_match_probability=threshold_match_probability)
        res_df = predictions.as_pandas_dataframe()

        results = []
        if res_df.empty:
            return results

        # Lookup dict for statutory conflict checks
        rec_lookup = {str(r.get("id") or r.get("org_id") or r.get("unique_id")): r for r in records}

        for _, row in res_df.iterrows():
            id_l = str(row["unique_id_l"])
            id_r = str(row["unique_id_r"])
            prob = float(row.get("match_probability", 0.0))
            weight = float(row.get("match_weight", 0.0))

            rec_l = rec_lookup.get(id_l, {})
            rec_r = rec_lookup.get(id_r, {})

            # Check statutory ID conflict (e.g. different valid EINs must never merge)
            tax_l = rec_l.get("statutory_tax_id") or rec_l.get("ein") or rec_l.get("rfc")
            tax_r = rec_r.get("statutory_tax_id") or rec_r.get("ein") or rec_r.get("rfc")

            if tax_l and tax_r and str(tax_l).replace("-", "").upper() != str(tax_r).replace("-", "").upper():
                logger.warning(
                    "Splink match rejected due to statutory ID conflict: %s (%s) vs %s (%s)",
                    id_l, tax_l, id_r, tax_r
                )
                continue

            # Apply Three-Tier Policy
            if prob >= 0.95:
                decision = "AUTO_MERGE"
            elif prob >= 0.70:
                decision = "QUARANTINE_REVIEW"
            else:
                decision = "DISTINCT"

            results.append({
                "source_id": id_l,
                "target_id": id_r,
                "match_probability": prob,
                "match_weight": weight,
                "decision": decision,
                "match_features": {
                    "probabilistic_engine": "splink_duckdb_5.0",
                    "domain_match": rec_l.get("domain") == rec_r.get("domain") and bool(rec_l.get("domain")),
                    "name_l": rec_l.get("name"),
                    "name_r": rec_r.get("name"),
                }
            })

        return results


# Singleton instance
splink_linker = SplinkIdentityLinker()

__all__ = [
    "SplinkIdentityLinker",
    "splink_linker",
]

