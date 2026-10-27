"""
Source configuration loader and registry for Mexican open-data sources and web directories.
Supports categorization into API and Public-Directory Scraping channels.
"""

import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional
from .settings import settings
from ..utils.logging import logger


@dataclass
class SourceConfig:
    name: str
    description: str
    enabled: bool
    type: str  # 'api', 'csv', 'json', 'web', 'file', 'directory'
    category: str = "api"  # 'api' or 'scraping'
    source_type: str = "official_api"  # 'official_api' or 'public_directory'
    priority: int = 50
    url: Optional[str] = None
    base_url: Optional[str] = None
    direct_resource_url: Optional[str] = None
    token_env: Optional[str] = None
    endpoints: Dict[str, str] = field(default_factory=dict)
    chunk_size: int = 5000
    is_bulk_enabled: bool = True
    is_compliance_only: bool = False
    rate_limit_per_second: int = 5
    default_tags: List[str] = field(default_factory=list)
    raw_config: Dict[str, Any] = field(default_factory=dict)


class SourceRegistry:
    """Manages source configurations loaded from YAML."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or settings.SOURCES_CONFIG_PATH
        self.sources: Dict[str, SourceConfig] = {}
        self.global_settings: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Loads and parses source configurations from YAML."""
        if not self.config_path.exists():
            logger.warn(f"Source configuration file not found at {self.config_path}, using defaults")
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        self.global_settings = data.get("settings", {})
        raw_sources = data.get("sources", {})

        for source_key, cfg in raw_sources.items():
            category_val = cfg.get("category", "api" if cfg.get("type") in ("api", "csv", "json") else "scraping")
            source_type_val = cfg.get("source_type", "official_api" if category_val == "api" else "public_directory")

            self.sources[source_key] = SourceConfig(
                name=cfg.get("name", source_key),
                description=cfg.get("description", ""),
                enabled=cfg.get("enabled", True),
                type=cfg.get("type", "csv"),
                category=category_val,
                source_type=source_type_val,
                priority=cfg.get("priority", 50),
                url=cfg.get("url"),
                base_url=cfg.get("base_url"),
                direct_resource_url=cfg.get("direct_resource_url"),
                token_env=cfg.get("token_env"),
                endpoints=cfg.get("endpoints", {}),
                chunk_size=cfg.get("chunk_size", 5000),
                is_bulk_enabled=cfg.get("is_bulk_enabled", True),
                is_compliance_only=cfg.get("is_compliance_only", False),
                rate_limit_per_second=cfg.get("rate_limit_per_second", 5),
                default_tags=cfg.get("default_tags", []),
                raw_config=cfg,
            )

    def get_source(self, key: str) -> Optional[SourceConfig]:
        return self.sources.get(key)

    def get_enabled_sources(self) -> Dict[str, SourceConfig]:
        return {k: v for k, v in self.sources.items() if v.enabled}

    def get_api_sources(self) -> Dict[str, SourceConfig]:
        """Returns all enabled API sources."""
        return {k: v for k, v in self.get_enabled_sources().items() if v.category == "api"}

    def get_scraping_sources(self) -> Dict[str, SourceConfig]:
        """Returns all enabled public-directory scraping sources."""
        return {k: v for k, v in self.get_enabled_sources().items() if v.category == "scraping"}


sources_registry = SourceRegistry()
