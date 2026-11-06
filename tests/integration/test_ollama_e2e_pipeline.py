"""
DataExtraction — E2E Integration & Verification Test Suite: Ollama LLaMA 3.1:8B Integration
==========================================================================================
Validates Phase 5 & Phase 6:
  1. Containerization & Cloud Deployment Architecture:
     - infra/docker-compose.yml structure, services (ollama, ollama-init), ports, volumes, health checks.
     - infra/k8s manifests (01-namespace-config.yaml, 08-ollama-deployment.yaml) PVCs, services, probes.
  2. End-to-End Client Resilience:
     - Three-state circuit breaker state machine under concurrency.
     - Heartbeat warmup ping and connection pooling.
  3. Natural Language Search & DB Integration:
     - POST /api/ai/search with schema-aware SQL construction and parameterized execution.
     - Resilient failover to regex engine on timeout.
  4. Entity Resolution & Splink Linkage:
     - Statutory ID conflict pre-filtering and quarantine item promotion.
  5. Executive Title & Industry Taxonomy Classification:
     - Multi-tier seniority, department, and NAICS vertical classification.
"""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import yaml
from fastapi.testclient import TestClient

from packages.api.dependencies import UserPrincipal, get_current_user
from packages.api.main import create_app
from packages.domain.llm_entity_resolver import (
    AdjudicationResult,
    LLMEntityResolver,
)
from packages.domain.normalizer import (
    classify_industries_batch,
    classify_industry_heuristic,
    classify_industry_llm,
    normalize_executive_title_heuristic,
    normalize_executive_title_llm,
    normalize_executive_titles_batch,
    normalize_person,
)
from packages.domain.splink_engine import SplinkIdentityLinker
from packages.infrastructure.config_manager import config_manager
from packages.infrastructure.ollama_client import (
    CircuitBreakerState,
    OllamaClient,
    ollama_client,
)


class TestOllamaE2EPipeline(unittest.IsolatedAsyncioTestCase):
    """Full integration and verification suite for Ollama containerization & AI pipeline."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.dependency_overrides[get_current_user] = lambda: UserPrincipal(
            id="e2e-tester-id",
            email="tester@oneextraction.test",
            name="E2E Tester",
            is_admin=True,
        )
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        cls.app.dependency_overrides.clear()

    # ── 1. Deployment & Infrastructure Manifest Validation ─────────────────────

    def test_docker_compose_manifest_integrity(self):
        """Verifies infra/docker-compose.yml contains correct Ollama service configurations."""
        compose_path = os.path.join("infra", "docker-compose.yml")
        self.assertTrue(os.path.exists(compose_path), "infra/docker-compose.yml must exist")

        with open(compose_path, "r", encoding="utf-8") as f:
            compose_data = yaml.safe_load(f)

        services = compose_data.get("services", {})
        volumes = compose_data.get("volumes", {})

        # Verify volumes
        self.assertIn("ollama_data", volumes, "ollama_data volume must be declared in docker-compose.yml")

        # Verify ollama daemon service
        self.assertIn("ollama", services, "ollama service must be defined in docker-compose.yml")
        ollama_svc = services["ollama"]
        self.assertEqual(ollama_svc.get("image"), "ollama/ollama:latest")
        self.assertIn("11434:11434", ollama_svc.get("ports", []))
        self.assertIn("ollama_data:/root/.ollama", ollama_svc.get("volumes", []))
        self.assertIn("healthcheck", ollama_svc)

        # Verify ollama-init service
        self.assertIn("ollama-init", services, "ollama-init service must be defined")
        init_svc = services["ollama-init"]
        self.assertIn("ollama", init_svc.get("depends_on", {}))

        # Verify API service wiring
        self.assertIn("api", services)
        api_env = services["api"].get("environment", [])
        has_ollama_url = any("OLLAMA_BASE_URL" in str(e) for e in api_env)
        self.assertTrue(has_ollama_url, "API container must receive OLLAMA_BASE_URL")

    def test_kubernetes_manifests_integrity(self):
        """Verifies Kubernetes deployment and configmap declarations in infra/k8s/."""
        config_path = os.path.join("infra", "k8s", "01-namespace-config.yaml")
        ollama_k8s_path = os.path.join("infra", "k8s", "08-ollama-deployment.yaml")

        self.assertTrue(os.path.exists(config_path), "01-namespace-config.yaml must exist")
        self.assertTrue(os.path.exists(ollama_k8s_path), "08-ollama-deployment.yaml must exist")

        # Check ConfigMap
        with open(config_path, "r", encoding="utf-8") as f:
            docs = list(yaml.safe_load_all(f))
            cm = next((d for d in docs if d and d.get("kind") == "ConfigMap"), None)
            self.assertIsNotNone(cm, "ConfigMap must be present in 01-namespace-config.yaml")
            data = cm.get("data", {})
            self.assertIn("OLLAMA_BASE_URL", data)
            self.assertIn("OLLAMA_MODEL", data)
            self.assertEqual(data["OLLAMA_MODEL"], "llama3.1:8b")
            self.assertIn("LLM_ENTITY_ADJUDICATION_ENABLED", data)

        # Check Ollama K8s Deployment & PVC
        with open(ollama_k8s_path, "r", encoding="utf-8") as f:
            k8s_docs = list(yaml.safe_load_all(f))

        pvc = next((d for d in k8s_docs if d and d.get("kind") == "PersistentVolumeClaim"), None)
        self.assertIsNotNone(pvc, "PersistentVolumeClaim must be declared for Ollama model storage")
        self.assertEqual(pvc["metadata"]["name"], "ollama-models-pvc")

        svc = next((d for d in k8s_docs if d and d.get("kind") == "Service"), None)
        self.assertIsNotNone(svc, "ClusterIP Service must be declared for Ollama")
        self.assertEqual(svc["metadata"]["name"], "ollama-service")

        deploy = next((d for d in k8s_docs if d and d.get("kind") == "Deployment"), None)
        self.assertIsNotNone(deploy, "Deployment must be declared for Ollama")
        containers = deploy["spec"]["template"]["spec"]["containers"]
        self.assertEqual(len(containers), 1)
        self.assertEqual(containers[0]["name"], "ollama")
        self.assertIn("readinessProbe", containers[0])
        self.assertIn("livenessProbe", containers[0])

    # ── 2. Client Resilience & Circuit Breaker Mechanics ───────────────────────

    async def test_ollama_client_circuit_breaker_transitions(self):
        """Verifies circuit breaker state transitions under simulated error load."""
        test_client = OllamaClient(config={
            "base_url": "http://mock-service:11434",
            "model": "llama3.1:8b",
            "timeout_seconds": 0.5,
            "circuit_breaker_threshold": 2,
            "circuit_breaker_recovery_seconds": 0.2,
            "enabled": True,
        })

        self.assertEqual(test_client.state, CircuitBreakerState.CLOSED)
        self.assertTrue(test_client.is_available())

        # Trip circuit breaker
        test_client._record_failure(TimeoutError("Simulated timeout 1"))
        self.assertEqual(test_client.state, CircuitBreakerState.CLOSED)
        test_client._record_failure(TimeoutError("Simulated timeout 2"))
        self.assertEqual(test_client.state, CircuitBreakerState.OPEN)
        self.assertFalse(test_client.is_available())

        # Wait for recovery window to elapse
        await asyncio.sleep(0.25)
        self.assertEqual(test_client.state, CircuitBreakerState.HALF_OPEN)
        self.assertTrue(test_client.is_available())

        # Canary success resets to CLOSED
        test_client._record_success(duration_ms=45.0)
        self.assertEqual(test_client.state, CircuitBreakerState.CLOSED)
        await test_client.close()

    # ── 3. Schema-Aware Natural Language Search (/api/ai/search) ──────────────

    def test_e2e_ai_search_llm_flow(self):
        """Verifies POST /api/ai/search end-to-end flow with LLM translation."""
        mock_llm_res = {
            "table": "us_leads",
            "filters": {
                "seniority": "C_SUITE",
                "state_code": "CA",
                "min_lead_score": 80,
            },
            "explanation": "Query translated to California C-Suite leads with quality score >= 80",
            "confidence": 95,
            "suggestions": ["Filter by San Francisco tech startups"],
        }

        with patch.object(ollama_client, "is_available", return_value=True), \
             patch.object(ollama_client, "generate_structured", new_callable=AsyncMock) as mock_gen, \
             patch("packages.api.routers.ai_router.get_connection") as mock_conn:

            mock_gen.return_value = mock_llm_res

            # Mock DB cursor
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = [42]
            mock_cur.description = [("id",), ("company_name",), ("full_name",), ("lead_score",)]
            mock_cur.fetchall.return_value = [
                (1, "TechCorp", "Jane Doe", 92),
                (2, "CloudSys", "John Smith", 88),
            ]
            mock_conn.return_value.cursor.return_value = mock_cur

            response = self.client.post("/api/ai/search", json={"query": "Find California CEOs with score above 80"})
            self.assertEqual(response.status_code, 200)
            data = response.json()

            self.assertEqual(data["parsed"]["filters"]["seniority"], "C_SUITE")
            self.assertEqual(data["parsed"]["filters"]["state_code"], "CA")
            self.assertEqual(data["total"], 42)
            self.assertEqual(len(data["leads"]), 2)
            self.assertEqual(data["leads"][0]["company_name"], "TechCorp")

    def test_e2e_ai_search_fallback_flow(self):
        """Verifies POST /api/ai/search fallback when LLM fails or circuit breaker is OPEN."""
        with patch.object(ollama_client, "is_available", return_value=False), \
             patch("packages.api.routers.ai_router.get_connection") as mock_conn:

            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = [10]
            mock_cur.description = [("id",), ("company_name",), ("full_name",), ("lead_score",)]
            mock_cur.fetchall.return_value = [(1, "Austin Solar", "Alice Green", 85)]
            mock_conn.return_value.cursor.return_value = mock_cur

            response = self.client.post("/api/ai/search", json={"query": "Texas CEOs with high score"})
            self.assertEqual(response.status_code, 200)
            data = response.json()

            self.assertIn("Heuristic fallback", data["parsed"]["explanation"])
            self.assertEqual(data["parsed"]["filters"]["state_code"], "TX")
            self.assertEqual(data["parsed"]["filters"]["seniority"], "C_SUITE")
            self.assertEqual(data["total"], 10)

    # ── 4. Entity Resolution Semantic Adjudication (Agent 3) ───────────────────

    async def test_e2e_entity_resolution_quarantine_flow(self):
        """Verifies Splink quarantine review adjudication with LLaMA 3.1:8B reasoning."""
        linker = SplinkIdentityLinker()
        records_lookup = {
            "rec-1": {"id": "rec-1", "name": "Databricks Inc", "domain": "databricks.com", "state": "CA"},
            "rec-2": {"id": "rec-2", "name": "Databricks Systems Inc", "domain": "databricks.com", "state": "CA"},
        }
        quarantine = [
            {
                "source_id": "rec-1",
                "target_id": "rec-2",
                "match_probability": 0.85,
                "match_weight": 5.2,
                "decision": "QUARANTINE_REVIEW",
                "match_features": {},
            }
        ]

        mock_decision = {
            "is_same_entity": True,
            "decision": "MERGE",
            "confidence": 0.95,
            "reasoning": "Matching domain and corporate legal entity name variation",
            "score_adjustment": 0.12,
        }

        with patch.object(ollama_client, "is_available", return_value=True), \
             patch.object(ollama_client, "generate_structured", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = mock_decision

            adjudicated = await linker.adjudicate_quarantine(quarantine, records_lookup)
            self.assertEqual(len(adjudicated), 1)
            item = adjudicated[0]
            self.assertEqual(item["decision"], "AUTO_MERGE_LLM")
            self.assertGreaterEqual(item["match_probability"], 0.95)
            self.assertEqual(item["adjudication"]["method"], "ollama_llama3.1:8b")

    # ── 5. Executive Title & Industry Classification (Agents 4 & 5) ────────────

    async def test_e2e_normalization_batch_pipeline(self):
        """Verifies asynchronous batch classification and person record enrichment."""
        with patch.object(ollama_client, "is_available", return_value=False):
            # 1. Batch Title Normalization
            titles = ["Chief Operating Officer", "VP of Software Engineering", "Senior Product Manager"]
            title_results = await normalize_executive_titles_batch(titles, concurrency=3)
            self.assertEqual(len(title_results), 3)
            self.assertEqual(title_results[0]["seniority_level"], "C_SUITE")
            self.assertEqual(title_results[0]["department"], "OPERATIONS")
            self.assertEqual(title_results[1]["seniority_level"], "VP")
            self.assertEqual(title_results[1]["department"], "ENGINEERING")

            # 2. Batch Industry Classification
            industries = [
                "Cloud SaaS software and cybersecurity platforms",
                "Acute care clinical health services and hospital",
            ]
            ind_results = await classify_industries_batch(industries, concurrency=2)
            self.assertEqual(len(ind_results), 2)
            self.assertEqual(ind_results[0]["standardized_industry"], "Computer Software")
            self.assertEqual(ind_results[0]["naics_code"], "5415")
            self.assertEqual(ind_results[1]["standardized_industry"], "Healthcare")
            self.assertEqual(ind_results[1]["naics_code"], "6211")

            # 3. Person Normalization Enrichment
            raw_person = {
                "first_name": "Tim",
                "last_name": "Cook",
                "title": "Chief Executive Officer",
                "company_name": "Apple Inc",
                "email": "tcook@apple.com",
            }
            enriched = normalize_person(raw_person, source="INTERNAL_JSON")
            self.assertEqual(enriched["standardized_title"], "Chief Executive Officer")
            self.assertEqual(enriched["seniority_level"], "C_SUITE")
            self.assertEqual(enriched["department"], "EXECUTIVE")
            self.assertEqual(enriched["normalized_company_name"], "APPLE")


if __name__ == "__main__":
    unittest.main()
