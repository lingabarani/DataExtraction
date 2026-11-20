"""
Pydantic Domain Models for B2B AI Chatbot.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4
from pydantic import BaseModel, Field


class FieldStatus(str, Enum):
    PRESENT = "PRESENT"
    MISSING = "MISSING"
    UNVERIFIED = "UNVERIFIED"
    CONFLICTING = "CONFLICTING"
    VERIFIED = "VERIFIED"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    CONFLICTING = "CONFLICTING"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_INVESTIGATION = "NEEDS_INVESTIGATION"


class FieldAssessment(BaseModel):
    field_name: str
    status: FieldStatus
    value: Any = None
    source: str = "database"
    source_url: Optional[str] = None
    evidence: Optional[str] = None
    confidence: float = 0.8
    notes: Optional[str] = None


class CompanyCompleteness(BaseModel):
    company_id: str
    company_name: str
    fields: Dict[str, FieldAssessment] = Field(default_factory=dict)
    is_complete: bool = False
    missing_fields: List[str] = Field(default_factory=list)


class CompletenessReport(BaseModel):
    total_companies: int = 0
    complete_count: int = 0
    incomplete_count: int = 0
    field_stats: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    missing_data_plan: List[Dict[str, Any]] = Field(default_factory=list)


class ChatIntent(BaseModel):
    intent_type: Literal["search", "refine_filter", "targeted_lookup", "general_qa"] = "search"
    industry: Optional[str] = None
    company_name: Optional[str] = None
    geography: Dict[str, Any] = Field(default_factory=dict)
    requested_fields: List[str] = Field(default_factory=list)
    requested_contacts: List[str] = Field(default_factory=list)
    verification_required: bool = False
    limit: int = 50
    filters: Dict[str, Any] = Field(default_factory=dict)
    is_follow_up: bool = False
    explanation: str = ""
    confidence: int = 85


class ChatSessionCreate(BaseModel):
    title: Optional[str] = "New Conversation"


class ChatSessionResponse(BaseModel):
    id: str
    user_id: str
    title: str
    context: Dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class ChatMessageRequest(BaseModel):
    content: str


class ChatMessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    structured_plan: Optional[Dict[str, Any]] = None
    completeness_report: Optional[Dict[str, Any]] = None
    results_summary: Optional[Dict[str, Any]] = None
    created_at: str


class ReviewItemResponse(BaseModel):
    id: str
    session_id: str
    run_id: Optional[str] = None
    company_id: str
    company_name: str
    field_name: str
    existing_value: Any = None
    discovered_value: Any
    source_url: Optional[str] = None
    source_type: str
    evidence: Optional[str] = None
    field_confidence: float = 0.8
    verification_status: str = "UNVERIFIED"
    conflict_details: Optional[Dict[str, Any]] = None
    review_status: str = "PENDING"
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    created_at: str


class ReviewActionRequest(BaseModel):
    notes: Optional[str] = None
    reason: Optional[str] = None
