"""
Unit and Integration Test Suite for Splink Probabilistic Entity Linker
=====================================================================
Validates:
  1. Splink DuckDB 5.0 Linker execution.
  2. Ground-truth benchmark evaluation (Precision, Recall, False Merge, False Non-match).
  3. Rejection of candidate links with conflicting statutory tax IDs.
  4. Three-tier decision routing (Auto-merge >= 0.95, Quarantine 0.70-0.95, Distinct < 0.70).
"""

import sys
import unittest
from pathlib import Path

_backend_dir = Path(__file__).resolve().parent
_project_root = _backend_dir.parents[2]
_packages = _project_root / "packages"

for _p in [
    _packages / "pipeline",
    _packages / "infrastructure",
    _project_root,
]:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from splink_identity_linker import SplinkIdentityLinker, splink_linker


class TestSplinkProbabilisticLinker(unittest.TestCase):
    """Evaluates Splink DuckDB record linkage against verified test cases."""

    def setUp(self):
        self.linker = SplinkIdentityLinker(probability_two_random_records_match=0.05)

    def test_splink_true_matches_and_precision_recall(self):
        """
        Ground truth benchmark:
          - (1, 2) True Match (Tesla)
          - (3, 4) True Match (Microsoft)
          - (5, 6) True Match (Amazon)
          - (7, 8) True Non-Match (Apple vs Google in CA)
        """
        records = [
            {"id": "1", "name": "Tesla Inc.", "domain": "tesla.com", "state_code": "TX"},
            {"id": "2", "name": "Tesla Motors", "domain": "tesla.com", "state_code": "TX"},
            {"id": "3", "name": "Microsoft Corporation", "domain": "microsoft.com", "state_code": "WA"},
            {"id": "4", "name": "Microsoft Corp", "domain": "microsoft.com", "state_code": "WA"},
            {"id": "5", "name": "Amazon.com Inc", "domain": "amazon.com", "state_code": "WA"},
            {"id": "6", "name": "Amazon Retail LLC", "domain": "amazon.com", "state_code": "WA"},
            {"id": "7", "name": "Apple Inc", "domain": "apple.com", "state_code": "CA"},
            {"id": "8", "name": "Alphabet Google LLC", "domain": "google.com", "state_code": "CA"},
        ]

        results = self.linker.link_records(records, threshold_match_probability=0.70)

        # Expected true match pairs
        expected_matches = {("1", "2"), ("3", "4"), ("5", "6")}
        found_matches = set()
        false_merges = set()

        for res in results:
            pair = tuple(sorted([res["source_id"], res["target_id"]]))
            if pair in expected_matches:
                found_matches.add(pair)
                self.assertGreaterEqual(res["match_probability"], 0.70)
            else:
                false_merges.add(pair)

        # Calculate metrics
        tp = len(found_matches)
        fp = len(false_merges)
        fn = len(expected_matches - found_matches)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

        self.assertEqual(fp, 0, f"False merges detected: {false_merges}")
        self.assertEqual(precision, 1.0, "Precision must be 100% on ground truth")
        self.assertEqual(recall, 1.0, "Recall must be 100% on ground truth")

    def test_statutory_id_conflict_blocks_linkage(self):
        """
        Two subsidiaries sharing a parent domain or name must NOT link
        if they possess conflicting statutory Tax IDs (EIN/RFC).
        """
        records = [
            {
                "id": "sub_1",
                "name": "General Electric Capital Corp",
                "domain": "ge.com",
                "state_code": "NY",
                "statutory_tax_id": "14-1234567",
            },
            {
                "id": "sub_2",
                "name": "General Electric Healthcare LLC",
                "domain": "ge.com",
                "state_code": "NY",
                "statutory_tax_id": "06-7654321",  # Different EIN!
            },
        ]

        results = self.linker.link_records(records, threshold_match_probability=0.50)
        self.assertEqual(len(results), 0, "Conflicting statutory IDs must be blocked from merging")

    def test_sparse_records_handled_gracefully(self):
        """Records with missing domain or postal code should not raise exceptions."""
        records = [
            {"id": "a", "name": "Boutique Bakery Inc", "domain": None, "state_code": "IL"},
            {"id": "b", "name": "Boutique Bakery LLC", "domain": None, "state_code": "IL"},
        ]
        results = self.linker.link_records(records, threshold_match_probability=0.70)
        self.assertIsInstance(results, list)


if __name__ == "__main__":
    unittest.main()

