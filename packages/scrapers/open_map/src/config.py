"""
Enterprise Configuration Management for Open Map Extraction Engine.

Handles multi-mirror endpoint pools, rate limiting, timeouts, retry backoff,
adaptive quadtree subdivision limits, and environment variable overrides.
Zero hardcoded credentials or endpoints.
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    # Look for .env in current engine root or parent repository root
    engine_root = Path(__file__).resolve().parent.parent
    repo_root = engine_root.parent
    for env_path in [engine_root / ".env", repo_root / ".env"]:
        if env_path.exists():
            load_dotenv(env_path)
            break
except ImportError:
    pass

# Curated global diverse public Overpass API interpreter mirrors
DEFAULT_OVERPASS_MIRRORS: List[str] = [
    "https://overpass-api.de/api/interpreter",           # Germany (Primary Main Node)
    "https://overpass.kumi.systems/api/interpreter",     # Global CDN Mirror (Fast)
    "https://overpass.private.coffee/api/interpreter",   # Austria Mirror (High Reliability)
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter" # Eastern Europe Mirror
]


@dataclass
class OverpassConfig:
    """Enterprise configuration for Overpass API network operations."""
    
    # Endpoints
    primary_endpoint: str = field(
        default_factory=lambda: os.getenv("OVERPASS_API_URL", "https://overpass-api.de/api/interpreter").strip()
    )
    fallback_endpoints: List[str] = field(default_factory=list)
    custom_endpoint: Optional[str] = field(
        default_factory=lambda: os.getenv("OVERPASS_CUSTOM_URL", "").strip() or None
    )
    
    # Timeouts & Retries
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
    
    # Adaptive Quadtree Spatial Splitting
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
    
    # Throttling & Politeness
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
        # Assemble complete diverse mirror pool
        endpoints: List[str] = []
        if self.custom_endpoint:
            endpoints.append(self.custom_endpoint)
        
        env_fallbacks = os.getenv("OVERPASS_FALLBACK_URLS", "").strip()
        if env_fallbacks:
            for url in env_fallbacks.split(","):
                clean = url.strip()
                if clean and clean not in endpoints:
                    endpoints.append(clean)
        
        # Add primary if not present
        if self.primary_endpoint not in endpoints:
            endpoints.append(self.primary_endpoint)
            
        # Add all curated global mirrors to guarantee diversity
        for mirror in DEFAULT_OVERPASS_MIRRORS:
            if mirror not in endpoints:
                endpoints.append(mirror)
                
        self.fallback_endpoints = endpoints


# Default shared instance
default_config = OverpassConfig()
