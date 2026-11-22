"""
Central Chatbot Orchestrator.
Coordinates Steps 1 to 6:
  Step 1: Natural-language understanding & structured search plan
  Step 2: Database-first search via AI Query
  Step 3: Field-level completeness analysis
  Step 4: Automatic Live Discovery fallback / targeted missing-field enrichment
  Step 5: Result merging, reconciliation & provenance tracking
  Step 6: Staging persistence (review queue) & final response generation
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Set
from uuid import uuid4

from packages.chatbot.core.completeness_analyzer import CompletenessAnalyzer
from packages.chatbot.core.result_merger import ResultMerger
from packages.chatbot.core.session_manager import SessionManager
from packages.chatbot.integrations.ai_query_client import AIQueryClient
from packages.chatbot.integrations.live_discovery_client import LiveDiscoveryClient
from packages.chatbot.integrations.llm_client import ChatbotLLMClient
from packages.chatbot.models import ChatIntent
from packages.chatbot.persistence.chat_repository import ChatRepository
from packages.chatbot.persistence.review_repository import ReviewRepository

logger = logging.getLogger("dataextraction.chatbot.orchestrator")


class ChatbotOrchestrator:
    def __init__(
        self,
        llm_client: Optional[ChatbotLLMClient] = None,
        ai_query_client: Optional[AIQueryClient] = None,
        live_discovery_client: Optional[LiveDiscoveryClient] = None,
        completeness_analyzer: Optional[CompletenessAnalyzer] = None,
        result_merger: Optional[ResultMerger] = None,
        chat_repo: Optional[ChatRepository] = None,
        review_repo: Optional[ReviewRepository] = None,
        session_manager: Optional[SessionManager] = None,
    ) -> None:
        self.llm_client = llm_client or ChatbotLLMClient()
        self.ai_query_client = ai_query_client or AIQueryClient()
        self.live_discovery_client = live_discovery_client or LiveDiscoveryClient()
        self.completeness_analyzer = completeness_analyzer or CompletenessAnalyzer()
        self.result_merger = result_merger or ResultMerger()
        self.chat_repo = chat_repo or ChatRepository()
        self.review_repo = review_repo or ReviewRepository()
        self.session_manager = session_manager or SessionManager(self.chat_repo)

        # In-memory tracking of active session cancellation flags
        self._cancelled_sessions: Set[str] = set()

    def cancel_session(self, session_id: str) -> None:
        self._cancelled_sessions.add(session_id)

    async def execute_chat_stream(
        self,
        session_id: str,
        user_id: str,
        prompt: str,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Executes conversational intelligence pipeline, streaming progressive SSE events.
        """
        t0 = time.time()
        self._cancelled_sessions.discard(session_id)

        # 0. Save User Message
        user_msg = self.chat_repo.add_message(
            session_id=session_id,
            role="user",
            content=prompt,
        )

        yield {
            "event": "message_received",
            "data": {"message_id": user_msg["id"], "prompt": prompt, "timestamp": time.time()},
        }

        # 1. Natural Language Understanding & Context Load
        yield {"event": "understanding_query", "data": {"status": "analyzing_intent"}}
        context = self.session_manager.get_context(session_id, user_id=user_id)
        intent = self.llm_client.parse_intent(prompt, context=context)

        # Update session title if first exchange
        title = prompt[:50] + ("..." if len(prompt) > 50 else "")
        self.session_manager.update_context_with_intent(session_id, intent, title=title)

        run_id = self.chat_repo.create_execution_run(
            session_id=session_id,
            message_id=user_msg["id"],
            run_type="database_only",
            plan=intent.model_dump(),
        )

        yield {
            "event": "search_plan",
            "data": {
                "run_id": run_id,
                "plan": intent.model_dump(),
                "explanation": intent.explanation,
            },
        }

        if session_id in self._cancelled_sessions:
            yield {"event": "error", "data": {"error": "Search cancelled by user"}}
            return

        # 2. Database-First Search
        yield {"event": "database_search", "data": {"status": "querying_postgresql"}}
        db_companies = self.ai_query_client.search_database(intent)
        yield {
            "event": "database_results",
            "data": {"count": len(db_companies), "preview": db_companies[:5]},
        }

        if session_id in self._cancelled_sessions:
            yield {"event": "error", "data": {"error": "Search cancelled by user"}}
            return

        # 3. Field-Level Completeness Analysis
        yield {"event": "checking_completeness", "data": {"status": "analyzing_requested_fields"}}
        completeness_rep = self.completeness_analyzer.analyze(
            companies=db_companies,
            requested_fields=intent.requested_fields,
            verification_required=intent.verification_required,
        )

        yield {
            "event": "completeness_report",
            "data": completeness_rep.model_dump(),
        }

        # 4. Live Discovery Fallback (if 0 DB results OR missing fields)
        discovered_orgs: List[Dict[str, Any]] = []
        needs_discovery = len(db_companies) == 0 or bool(completeness_rep.missing_data_plan)

        if needs_discovery:
            yield {
                "event": "live_discovery_started",
                "data": {
                    "reason": "zero_db_matches" if len(db_companies) == 0 else "missing_requested_fields",
                    "missing_count": len(completeness_rep.missing_data_plan),
                },
            }

            try:
                # If zero DB matches, run general federated discovery
                if len(db_companies) == 0:
                    async for disc_event in self.live_discovery_client.run_discovery_stream(intent, timeout=20.0):
                        if session_id in self._cancelled_sessions:
                            break
                        evt_type = disc_event.get("type")
                        if evt_type == "source_status":
                            yield {"event": "discovery_progress", "data": disc_event}
                        elif evt_type in ("snapshot", "answer", "result", "cards_snapshot"):
                            raw_results = disc_event.get("cards") or disc_event.get("results") or disc_event.get("preview") or []
                            if raw_results:
                                discovered_orgs = raw_results
                                yield {"event": "discovery_results", "data": {"count": len(discovered_orgs), "results": discovered_orgs[:5]}}
                else:
                    # Targeted enrichment for missing fields on existing DB companies
                    targeted_enriched = await self.live_discovery_client.discover_missing_fields_for_companies(
                        completeness_rep.missing_data_plan,
                        timeout=15.0,
                    )
                    for item in targeted_enriched:
                        d_data = item.get("discovered_data", {})
                        d_data["matched_company_id"] = item.get("target_company_id")
                        discovered_orgs.append(d_data)

                    yield {
                        "event": "discovery_results",
                        "data": {"count": len(discovered_orgs), "targeted": True},
                    }
            except Exception as disc_err:
                logger.warning("Live discovery encountered an error: %s", disc_err)
                yield {"event": "discovery_warning", "data": {"warning": str(disc_err)}}

        # 5. Result Merging, Reconciliation & Provenance Tracking
        yield {"event": "merging_results", "data": {"status": "reconciling_entities"}}
        merged_companies, staged_items = self.result_merger.merge_and_stage(
            session_id=session_id,
            db_companies=db_companies,
            discovered_orgs=discovered_orgs,
            run_id=run_id,
        )

        # 6. Review/Staging Persistence (Save newly discovered facts as PENDING)
        staged_count = 0
        if staged_items:
            yield {"event": "saving_for_review", "data": {"count": len(staged_items)}}
            for s_item in staged_items:
                try:
                    self.review_repo.add_review_item(
                        session_id=session_id,
                        run_id=run_id,
                        company_id=s_item["company_id"],
                        company_name=s_item["company_name"],
                        field_name=s_item["field_name"],
                        discovered_value=s_item["discovered_value"],
                        source_type=s_item["source_type"],
                        source_url=s_item.get("source_url"),
                        existing_value=s_item.get("existing_value"),
                        evidence=s_item.get("evidence"),
                        field_confidence=s_item.get("field_confidence", 0.8),
                        verification_status=s_item.get("verification_status", "UNVERIFIED"),
                        conflict_details=s_item.get("conflict_details"),
                    )
                    staged_count += 1
                except Exception as r_err:
                    logger.warning("Failed to stage review item: %s", r_err)

        # Update execution run record
        run_type = "live_discovery_fallback" if needs_discovery else "database_only"
        duration_ms = int((time.time() - t0) * 1000)
        self.chat_repo.update_execution_run(
            run_id=run_id,
            status="completed",
            db_matches_count=len(db_companies),
            discovered_matches_count=len(discovered_orgs),
            timings={"total_ms": duration_ms},
        )

        # 7. Generate Natural-Language Answer
        answer_text = self.llm_client.generate_conversational_response(
            query=prompt,
            intent=intent,
            db_results=db_companies,
            discovered_results=discovered_orgs,
            completeness_report=completeness_rep.model_dump(),
            staged_reviews_count=staged_count,
            company_context=context.get("company_context") if context else None,
        )

        # 8. Save Assistant Message
        asst_msg = self.chat_repo.add_message(
            session_id=session_id,
            role="assistant",
            content=answer_text,
            structured_plan=intent.model_dump(),
            completeness_report=completeness_rep.model_dump(),
            results_summary={
                "total_companies": len(merged_companies),
                "db_count": len(db_companies),
                "discovered_count": len(discovered_orgs),
                "staged_reviews_count": staged_count,
            },
        )

        # Update context
        self.session_manager.update_context_with_intent(
            session_id=session_id,
            intent=intent,
            search_id=run_id,
            results_count=len(merged_companies),
        )

        yield {
            "event": "answer",
            "data": {
                "message_id": asst_msg["id"],
                "content": answer_text,
                "companies": merged_companies,
                "staged_reviews_count": staged_count,
            },
        }

        yield {
            "event": "done",
            "data": {
                "session_id": session_id,
                "run_id": run_id,
                "total_companies": len(merged_companies),
                "duration_ms": duration_ms,
            },
        }
