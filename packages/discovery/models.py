"""
Discovery Domain Models & Data Structures.
Defines normalized schemas for organizations, people, facts, search intents, and source results.
Includes 'unavailable' status for sources that cannot reach their upstream service.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4
from pydantic import BaseModel, Field, model_validator


EmailLabel = Literal["found", "inferred", "verified"]
SourceStatusType = Literal["ok", "empty", "blocked", "error", "unavailable", "timeout", "running"]


class EmailEntry(BaseModel):
    value: str
    label: EmailLabel = "inferred"
    source_url: Optional[str] = None
    confidence: float = 0.5


class PhoneEntry(BaseModel):
    number: str
    type: Optional[str] = "work"
    label: Optional[str] = None
    source_url: Optional[str] = None
    verified: bool = False


class FactRecord(BaseModel):
    entity_type: str  # "organization" | "person"
    entity_id: str
    field: str
    value: Any
    source: str
    source_url: Optional[str] = None
    retrieved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    confidence: float = 0.8


class PersonRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = ""
    full_name: str = ""
    normalized_name: str = ""
    title: Optional[str] = None
    role_type: Optional[str] = None  # owner, administrator, director_of_nursing, executive, staff
    org_id: Optional[str] = None
    org_name: Optional[str] = None
    headline: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = "US"
    profile_urls: List[str] = Field(default_factory=list)
    emails: List[EmailEntry] = Field(default_factory=list)
    phones: List[PhoneEntry] = Field(default_factory=list)
    provenance: str = "discovery"
    verified: bool = False
    suppressed: bool = False
    confidence: float = 0.8
    source_url: Optional[str] = None

    @model_validator(mode="after")
    def sync_names(self) -> PersonRecord:
        if not self.full_name and self.name:
            self.full_name = self.name
        elif not self.name and self.full_name:
            self.name = self.full_name
        if not self.normalized_name and self.name:
            self.normalized_name = self.name.lower().strip()
        if not self.state and self.region:
            self.state = self.region
        return self


class OrgRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = ""
    canonical_name: str = ""
    normalized_name: str = ""
    category: Optional[str] = None
    subcategories: List[str] = Field(default_factory=list)
    address: Dict[str, Any] = Field(default_factory=dict)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    phones: List[PhoneEntry] = Field(default_factory=list)
    emails: List[EmailEntry] = Field(default_factory=list)
    website: Optional[str] = None
    domain: Optional[str] = None
    hours: List[Dict[str, Any]] = Field(default_factory=list)
    rating: Optional[float] = None
    review_count: Optional[int] = None
    services: List[str] = Field(default_factory=list)
    regulatory: Dict[str, Any] = Field(default_factory=dict)  # CMS star rating, ownership, NC license
    social: Dict[str, Any] = Field(default_factory=dict)      # linkedin, facebook, twitter
    people: List[PersonRecord] = Field(default_factory=list)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    quality_score: float = 0.5
    confidence: float = 0.8
    verified: bool = False
    first_seen_source: str = "discovery"
    metadata: Dict[str, Any] = Field(default_factory=dict)
    first_seen: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_seen: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @model_validator(mode="after")
    def sync_names(self) -> OrgRecord:
        if not self.canonical_name and self.name:
            self.canonical_name = self.name
        elif not self.name and self.canonical_name:
            self.name = self.canonical_name
        if not self.normalized_name and self.name:
            self.normalized_name = self.name.lower().strip()
        return self


class SourceStatus(BaseModel):
    name: str = ""
    source: str = ""
    status: SourceStatusType = "ok"
    count: int = 0
    record_count: int = 0
    elapsed_ms: int = 0
    message: Optional[str] = None
    error_message: Optional[str] = None

    @model_validator(mode="after")
    def sync_fields(self) -> SourceStatus:
        if not self.name and self.source:
            self.name = self.source
        elif not self.source and self.name:
            self.source = self.name
        if not self.count and self.record_count:
            self.count = self.record_count
        elif not self.record_count and self.count:
            self.record_count = self.count
        if not self.message and self.error_message:
            self.message = self.error_message
        elif not self.error_message and self.message:
            self.error_message = self.message
        return self


class SourceResult(BaseModel):
    source: str = ""
    status: Optional[SourceStatus] = None
    organizations: List[OrgRecord] = Field(default_factory=list)
    orgs: List[OrgRecord] = Field(default_factory=list)
    record: Optional[OrgRecord] = None
    people: List[PersonRecord] = Field(default_factory=list)
    facts: List[FactRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_lists(self) -> SourceResult:
        if not self.organizations and self.orgs:
            self.organizations = self.orgs
        elif not self.orgs and self.organizations:
            self.orgs = self.organizations
        if not self.record and self.organizations:
            self.record = self.organizations[0]
        return self


class SearchIntent(BaseModel):
    query: str
    categories: List[str] = Field(default_factory=list)
    synonyms: List[str] = Field(default_factory=list)
    geography: Dict[str, Any] = Field(default_factory=dict)
    want: List[str] = Field(default_factory=lambda: ["organizations", "people", "reviews", "contacts"])
    filters: Dict[str, Any] = Field(default_factory=dict)


@dataclass
class Budget:
    total_seconds: float = 45.0
    deadline: float = field(default_factory=lambda: time.monotonic() + 45.0)

    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def is_expired(self) -> bool:
        return self.remaining() <= 0.0
