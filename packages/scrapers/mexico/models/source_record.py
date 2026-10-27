"""
Source record models for preserving data provenance across all ingestion sources.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, Dict, Any


@dataclass
class SourceProvenanceRecord:
    """Represents the provenance of a data point from an official source."""
    source: str
    source_record_id: str
    source_url: str
    retrieved_at: str
    source_updated_at: Optional[str] = None
    raw_hash: Optional[str] = None
    raw_payload_data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Avoid cluttering exported JSON with full duplicate raw dump unless debugging
        d.pop("raw_payload_data", None)
        return d


@dataclass
class RawSourcePayload:
    """Holds a raw record payload along with its metadata before normalization."""
    source: str
    source_record_id: str
    source_url: str
    raw_data: Dict[str, Any]
    retrieved_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    raw_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
