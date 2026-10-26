"""
Enterprise Configuration Management for Open Map Extraction Engine.
Embedded in OneExtraction platform.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    from dotenv import load_dotenv
    # Search for .env in botasaurus, engine root, or repo root
    _curr = Path(__file__).resolve().parent
    for env_path in [
        _curr.parent / ".env",
        _curr.parent.parent / "Open Map Extraction Engine" / ".env",
        _curr.parent.parent / ".env"
    ]:
        if env_path.exists():
            load_dotenv(env_path)
            break
except ImportError:
    pass

DEFAULT_OVERPASS_MIRRORS: List[str] = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
]


@dataclass
class OverpassConfig:
    """Enterprise configuration for Overpass API network operations."""

    primary_endpoint: str = field(
        default_factory=lambda: os.getenv("OVERPASS_API_URL", "https://overpass-api.de/api/interpreter").strip()
    )
    fallback_endpoints: List[str] = field(default_factory=list)
    custom_endpoint: Optional[str] = field(
        default_factory=lambda: os.getenv("OVERPASS_CUSTOM_URL", "").strip() or None
    )

    connect_timeout_sec: int = field(
        default_factory=lambda: int(os.getenv("OVERPASS_CONNECT_TIMEOUT_SEC", "10"))
    )
    read_timeout_sec: int = field(
        default_factory=lambda: int(os.getenv("OVERPASS_READ_TIMEOUT_SEC", "45"))
    )
    query_server_timeout_sec: int = field(
        default_factory=lambda: int(os.getenv("OVERPASS_SERVER_TIMEOUT_SEC", "35"))
    )
    max_retries: int = field(
        default_factory=lambda: int(os.getenv("OVERPASS_MAX_RETRIES", "3"))
    )
    backoff_factor: float = field(
        default_factory=lambda: float(os.getenv("OVERPASS_BACKOFF_FACTOR", "1.5"))
    )
    circuit_breaker_cooldown_sec: float = field(
        default_factory=lambda: float(os.getenv("OVERPASS_CIRCUIT_COOLDOWN_SEC", "120.0"))
    )

    enable_adaptive_subdivision: bool = field(
        default_factory=lambda: os.getenv("OVERPASS_ADAPTIVE_SUBDIVISION", "true").lower() in ("1", "true", "yes")
    )
    max_quadtree_depth: int = field(
        default_factory=lambda: int(os.getenv("OVERPASS_MAX_QUADTREE_DEPTH", "3"))
    )
    chunk_size_deg: float = field(
        default_factory=lambda: float(os.getenv("OVERPASS_CHUNK_SIZE_DEG", "0.5"))
    )
    min_chunk_deg: float = field(
        default_factory=lambda: float(os.getenv("OVERPASS_MIN_CHUNK_DEG", "0.0625"))
    )

    rate_limit_delay_sec: float = field(
        default_factory=lambda: float(os.getenv("OVERPASS_RATE_LIMIT_DELAY", "1.2"))
    )
    contact_email: str = field(
        default_factory=lambda: os.getenv("OVERPASS_CONTACT_EMAIL", "researcher.contact@gmail.com").strip()
    )
    user_agent: str = field(
        default_factory=lambda: os.getenv(
            "OVERPASS_USER_AGENT",
            f"DataExtractionProject-OSMCollector/2.0 (Open Data Lead Research; {os.getenv('OVERPASS_CONTACT_EMAIL', 'researcher.contact@gmail.com')})"
        )
    )

    def __post_init__(self):
        endpoints: List[str] = []
        if self.custom_endpoint:
            endpoints.append(self.custom_endpoint)

        env_fallbacks = os.getenv("OVERPASS_FALLBACK_URLS", "").strip()
        if env_fallbacks:
            for url in env_fallbacks.split(","):
                clean = url.strip()
                if clean and clean not in endpoints:
                    endpoints.append(clean)

        if self.primary_endpoint not in endpoints:
            endpoints.append(self.primary_endpoint)

        for mirror in DEFAULT_OVERPASS_MIRRORS:
            if mirror not in endpoints:
                endpoints.append(mirror)

        self.fallback_endpoints = endpoints


default_config = OverpassConfig()
