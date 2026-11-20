"""
Session and Conversation Context Manager.
Maintains persistent conversation state, handles follow-up context resolution,
and guarantees user/tenant isolation.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from packages.chatbot.models import ChatIntent
from packages.chatbot.persistence.chat_repository import ChatRepository

logger = logging.getLogger("dataextraction.chatbot.session_manager")


class SessionManager:
    def __init__(self, repo: Optional[ChatRepository] = None) -> None:
        self.repo = repo or ChatRepository()

    def get_or_create_session(
        self,
        session_id: Optional[str] = None,
        user_id: str = "anonymous",
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        if session_id:
            sess = self.repo.get_session(session_id, user_id=user_id)
            if sess:
                return sess

        return self.repo.create_session(user_id=user_id, title=title or "New Conversation")

    def get_context(self, session_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        sess = self.repo.get_session(session_id)
        if not sess:
            return {}
        return sess.get("context", {})

    def update_context_with_intent(
        self,
        session_id: str,
        intent: ChatIntent,
        search_id: Optional[str] = None,
        results_count: int = 0,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        current_ctx = self.get_context(session_id)

        # Merge new intent into context
        updated_ctx: Dict[str, Any] = dict(current_ctx)
        if intent.industry:
            updated_ctx["industry"] = intent.industry
        if intent.company_name:
            updated_ctx["company_name"] = intent.company_name
        if intent.geography:
            updated_ctx["geography"] = {**updated_ctx.get("geography", {}), **intent.geography}
        if intent.requested_fields:
            existing_fields = set(updated_ctx.get("requested_fields", []))
            existing_fields.update(intent.requested_fields)
            updated_ctx["requested_fields"] = list(existing_fields)
        if intent.verification_required:
            updated_ctx["verification_required"] = True
        if intent.filters:
            updated_ctx["filters"] = {**updated_ctx.get("filters", {}), **intent.filters}

        if search_id:
            updated_ctx["previous_search_id"] = search_id
            updated_ctx["previous_results_count"] = results_count

        self.repo.update_session_context(session_id, updated_ctx, title=title)
        return updated_ctx

    def get_recent_history(self, session_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        return self.repo.list_messages(session_id, limit=limit)
