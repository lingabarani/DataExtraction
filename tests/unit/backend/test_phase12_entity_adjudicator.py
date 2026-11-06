"""
DataExtraction — Unit Test Suite: Agent 3 Entity Resolution Semantic Adjudicator
================================================================================
Validates:
  1. Statutory tax ID conflict detection (deterministic rejection).
  2. Statutory tax ID identity confirmation (deterministic merge).
  3. LLM semantic adjudication using Ollama LLaMA 3.1:8B structured response.
  4. Instant deterministic fallback when Ollama is unavailable or times out.
  5. Splink probabilistic quarantine queue adjudication integration.
  6. Batch adjudication with concurrency management.
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from packages.domain.llm_entity_resolver import (
    AdjudicationResult,
    LLMEntityResolver,
    llm_entity_resolver,
)
from packages.domain.splink_engine import SplinkIdentityLinker
from packages.infrastructure.ollama_client import ollama_client


class TestEntityResolutionAdjudicator(unittest.IsolatedAsyncioTestCase):
    """Test suite for Agent 3 Entity Resolution Semantic Adjudicator."""

    async def asyncSetUp(self):
        self.resolver = LLMEntityResolver(config={
            "entity_adjudication_enabled": True,
            "entity_adjudication_timeout": 2.0,
            "batch_concurrency": 3,
        })

    def test_statutory_precedence_matching_ein(self):
        """Verifies deterministic merge when statutory EINs match identically."""
        rec_a = {"id": "comp-1", "name": "Acme Corp", "ein": "12-3456789"}
        rec_b = {"id": "comp-2", "name": "Acme Corporation", "statutory_tax_id": "123456789"}

        res = self.resolver.check_statutory_precedence(rec_a, rec_b)
        self.assertIsNotNone(res)
        same, decision, reason = res
        self.assertTrue(same)
        self.assertEqual(decision, "MERGE")
        self.assertIn("matching statutory tax ID", reason)

    def test_statutory_precedence_conflicting_ein(self):
        """Verifies deterministic rejection when statutory EINs are distinct."""
        rec_a = {"id": "comp-1", "name": "Alpha Corp", "ein": "11-1111111"}
        rec_b = {"id": "comp-2", "name": "Alpha Holdings", "ein": "22-2222222"}

        res = self.resolver.check_statutory_precedence(rec_a, rec_b)
        self.assertIsNotNone(res)
        same, decision, reason = res
        self.assertFalse(same)
        self.assertEqual(decision, "SEPARATE")
        self.assertIn("distinct statutory tax IDs", reason)

    async def test_llm_adjudication_success(self):
        """Verifies semantic adjudication when Ollama returns structured JSON decision."""
        rec_a = {
            "id": "comp-100",
            "name": "Stripe Payments Company",
            "domain": "stripe.com",
            "state": "DE",
            "address": "123 Corporate Way, Wilmington, DE",
        }
        rec_b = {
            "id": "comp-200",
            "name": "Stripe Inc DBA Stripe Payments",
            "domain": "stripe.com",
            "state": "CA",
            "address": "510 Townsend St, San Francisco, CA",
        }

        mock_llm_output = {
            "is_same_entity": True,
            "decision": "MERGE",
            "confidence": 0.94,
            "reasoning": "Record 2 is the operational headquarters and parent company of Delaware subsidiary Record 1.",
            "score_adjustment": 0.12,
        }

        with patch.object(ollama_client, "is_available", return_value=True), \
             patch.object(ollama_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_llm_output

            adj = await self.resolver.adjudicate_pair(rec_a, rec_b, prior_prob=0.82)

            self.assertTrue(adj.is_same_entity)
            self.assertEqual(adj.decision, "MERGE")
            self.assertEqual(adj.confidence, 0.94)
            self.assertEqual(adj.method, "ollama_llama3.1:8b")
            self.assertIn("subsidiary", adj.reasoning)

    async def test_heuristic_fallback_when_ollama_times_out(self):
        """Verifies deterministic rule fallback when LLM fails or times out."""
        rec_a = {
            "id": "comp-300",
            "name": "Databricks Systems LLC",
            "domain": "databricks.com",
            "state": "CA",
        }
        rec_b = {
            "id": "comp-400",
            "name": "Databricks Inc",
            "domain": "databricks.com",
            "state": "CA",
        }

        with patch.object(ollama_client, "is_available", return_value=True), \
             patch.object(ollama_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = None  # Simulate timeout

            adj = await self.resolver.adjudicate_pair(rec_a, rec_b, prior_prob=0.88)

            self.assertTrue(adj.is_same_entity)
            self.assertEqual(adj.decision, "MERGE")
            self.assertEqual(adj.method, "deterministic_fallback")
            self.assertIn("databricks.com", adj.reasoning)

    async def test_splink_quarantine_integration(self):
        """Verifies SplinkIdentityLinker.adjudicate_quarantine upgrades matches."""
        linker = SplinkIdentityLinker()

        records_lookup = {
            "comp-1": {"id": "comp-1", "name": "Vercel Cloud Inc", "domain": "vercel.com", "state": "CA"},
            "comp-2": {"id": "comp-2", "name": "Vercel Inc", "domain": "vercel.com", "state": "CA"},
        }

        quarantine_results = [
            {
                "source_id": "comp-1",
                "target_id": "comp-2",
                "match_probability": 0.82,
                "match_weight": 4.5,
                "decision": "QUARANTINE_REVIEW",
                "match_features": {},
            }
        ]

        mock_llm_output = {
            "is_same_entity": True,
            "decision": "MERGE",
            "confidence": 0.96,
            "reasoning": "Identical root domain and corporate name.",
            "score_adjustment": 0.15,
        }

        with patch.object(ollama_client, "is_available", return_value=True), \
             patch.object(ollama_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_llm_output

            adjudicated = await linker.adjudicate_quarantine(quarantine_results, records_lookup)

            self.assertEqual(len(adjudicated), 1)
            item = adjudicated[0]
            self.assertEqual(item["decision"], "AUTO_MERGE_LLM")
            self.assertGreaterEqual(item["match_probability"], 0.95)
            self.assertIn("adjudication", item)
            self.assertEqual(item["adjudication"]["method"], "ollama_llama3.1:8b")

    async def test_batch_adjudication_concurrency(self):
        """Verifies adjudicate_batch processes multiple pairs concurrently."""
        pairs = [
            (
                {"id": f"comp-a-{i}", "name": f"Company {i} Inc", "domain": f"comp{i}.com"},
                {"id": f"comp-b-{i}", "name": f"Company {i} LLC", "domain": f"comp{i}.com"},
                0.85,
            )
            for i in range(5)
        ]

        with patch.object(self.resolver, "adjudicate_pair", new_callable=AsyncMock) as mock_adj:
            mock_adj.return_value = AdjudicationResult(
                source_id="a",
                target_id="b",
                is_same_entity=True,
                decision="MERGE",
                confidence=0.90,
                reasoning="Batch processed",
                score_adjustment=0.10,
                method="mock",
            )

            results = await self.resolver.adjudicate_batch(pairs)
            self.assertEqual(len(results), 5)
            self.assertEqual(mock_adj.call_count, 5)


if __name__ == "__main__":
    unittest.main()

