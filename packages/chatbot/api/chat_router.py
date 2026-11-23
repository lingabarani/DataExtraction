"""
FastAPI Router for B2B AI Chatbot.
Provides REST and SSE endpoints for session lifecycle, conversational search,
execution streaming, and discovery review/approval queue.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from packages.api.dependencies import UserPrincipal, get_current_user
from packages.chatbot.core.orchestrator import ChatbotOrchestrator
from packages.chatbot.models import (
    ChatMessageRequest,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionResponse,
    ReviewActionRequest,
    ReviewItemResponse,
)
from packages.chatbot.persistence.chat_repository import ChatRepository
from packages.chatbot.persistence.review_repository import ReviewRepository

logger = logging.getLogger("dataextraction.chatbot.api")

router = APIRouter(prefix="/api/v1/chat", tags=["B2B AI Chatbot"])

# Singleton instances
_chat_repo = ChatRepository()
_review_repo = ReviewRepository()
_orchestrator = ChatbotOrchestrator(chat_repo=_chat_repo, review_repo=_review_repo)


# ── Session Management ────────────────────────────────────────────────────────

@router.post("/sessions", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    body: ChatSessionCreate = ChatSessionCreate(),
    user: UserPrincipal = Depends(get_current_user),
):
    """Creates a new persistent conversation session."""
    initial_ctx = {"company_context": body.company_context} if body.company_context else {}
    sess = _chat_repo.create_session(
        user_id=user.id,
        title=body.title or "New Conversation",
        context=initial_ctx,
    )
    return sess


@router.get("/sessions", response_model=List[ChatSessionResponse])
def list_sessions(
    limit: int = Query(50, ge=1, le=100),
    user: UserPrincipal = Depends(get_current_user),
):
    """Lists recent conversation sessions for the authenticated user."""
    return _chat_repo.list_sessions(user_id=user.id, limit=limit)


@router.get("/sessions/{session_id}", response_model=ChatSessionResponse)
def get_session(
    session_id: str,
    user: UserPrincipal = Depends(get_current_user),
):
    """Gets details and structured context for a conversation session."""
    sess = _chat_repo.get_session(session_id, user_id=user.id)
    if not sess:
        raise HTTPException(status_code=404, detail="Conversation session not found")
    return sess


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str,
    user: UserPrincipal = Depends(get_current_user),
):
    """Deletes a conversation session and all its messages."""
    deleted = _chat_repo.delete_session(session_id, user_id=user.id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation session not found")
    return None


@router.get("/sessions/{session_id}/history", response_model=List[ChatMessageResponse])
def get_session_history(
    session_id: str,
    limit: int = Query(100, ge=1, le=200),
    user: UserPrincipal = Depends(get_current_user),
):
    """Retrieves chronological message history for a conversation session."""
    sess = _chat_repo.get_session(session_id, user_id=user.id)
    if not sess:
        raise HTTPException(status_code=404, detail="Conversation session not found")
    return _chat_repo.list_messages(session_id, limit=limit)


# ── Messaging & SSE Streaming ─────────────────────────────────────────────────

@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    body: ChatMessageRequest,
    user: UserPrincipal = Depends(get_current_user),
):
    """
    Submits a message and returns the complete final answer synchronously.
    For progressive updates, use the SSE /stream endpoint.
    """
    sess = _chat_repo.get_session(session_id, user_id=user.id)
    if not sess:
        raise HTTPException(status_code=404, detail="Conversation session not found")

    if body.company_context:
        ctx = sess.get("context") or {}
        ctx["company_context"] = body.company_context
        _chat_repo.update_session_context(session_id, ctx)

    final_answer = None
    async for event in _orchestrator.execute_chat_stream(session_id, user.id, body.content):
        if event.get("event") == "answer":
            final_answer = event.get("data")

    return final_answer or {"status": "completed"}


@router.get("/sessions/{session_id}/stream")
async def stream_chat(
    session_id: str,
    prompt: str = Query(..., description="User query prompt"),
    company_context: Optional[str] = Query(None, description="Optional JSON-encoded company context"),
    user: UserPrincipal = Depends(get_current_user),
):
    """
    Server-Sent Events (SSE) endpoint streaming pipeline execution:
    message_received -> understanding_query -> search_plan -> database_search ->
    database_results -> checking_completeness -> live_discovery_started ->
    discovery_progress -> discovery_results -> merging_results -> saving_for_review -> answer -> done.
    """
    sess = _chat_repo.get_session(session_id, user_id=user.id)
    if not sess:
        raise HTTPException(status_code=404, detail="Conversation session not found")

    if company_context:
        try:
            parsed_ctx = json.loads(company_context)
            ctx = sess.get("context") or {}
            ctx["company_context"] = parsed_ctx
            _chat_repo.update_session_context(session_id, ctx)
        except Exception:
            pass

    async def event_generator():
        try:
            async for event_payload in _orchestrator.execute_chat_stream(session_id, user.id, prompt):
                event_name = event_payload.get("event", "message")
                data_str = json.dumps(event_payload.get("data", {}))
                yield f"event: {event_name}\ndata: {data_str}\n\n"
        except asyncio.CancelledError:
            logger.info("SSE client disconnected for session %s", session_id)
        except Exception as exc:
            logger.error("SSE stream error: %s", exc)
            err_data = json.dumps({"error": str(exc)})
            yield f"event: error\ndata: {err_data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sessions/{session_id}/cancel")
def cancel_execution(
    session_id: str,
    user: UserPrincipal = Depends(get_current_user),
):
    """Cancels active Live Discovery or query execution for the session."""
    _orchestrator.cancel_session(session_id)
    return {"status": "cancelled", "session_id": session_id}


# ── Staged Review Queue Endpoints ─────────────────────────────────────────────

@router.get("/reviews", response_model=List[ReviewItemResponse])
def list_review_queue(
    status: Optional[str] = Query(None, description="Filter by status: PENDING, APPROVED, REJECTED"),
    session_id: Optional[str] = Query(None),
    company_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: UserPrincipal = Depends(get_current_user),
):
    """Lists staged discovery items awaiting human verification or audit history."""
    return _review_repo.list_review_items(
        status=status,
        session_id=session_id,
        company_id=company_id,
        limit=limit,
        offset=offset,
    )


@router.get("/reviews/stats")
def get_review_queue_stats(
    user: UserPrincipal = Depends(get_current_user),
):
    """Returns summary counts of pending, approved, and rejected reviews."""
    return _review_repo.get_review_stats()


@router.post("/reviews/{item_id}/action", response_model=ReviewItemResponse)
def execute_review_action(
    item_id: str,
    body: ReviewActionRequest,
    user: UserPrincipal = Depends(get_current_user),
):
    """Applies human review decision (approve or reject) to a staged discovery item."""
    item = _review_repo.get_review_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Review item not found")

    if body.action.upper() == "APPROVE":
        success = _review_repo.approve_review_item(item_id, reviewer=user.email, notes=body.reason)
    elif body.action.upper() == "REJECT":
        success = _review_repo.reject_review_item(item_id, reviewer=user.email, reason=body.reason)
    else:
        raise HTTPException(status_code=400, detail="Invalid action. Must be APPROVE or REJECT.")

    if not success:
        raise HTTPException(status_code=400, detail="Could not apply action. Item may have already been resolved.")

    updated_item = _review_repo.get_review_item(item_id)
    return updated_item
