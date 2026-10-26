import time
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger("USBusinessCollector")

class BaseSource(ABC):
    """Abstract base class for all public open data sources."""

    def __init__(self, name: str, source_type: str, base_url: str, rate_limit_delay: float = 0.5):
        self.name = name
        self.source_type = source_type
        self.base_url = base_url
        self.rate_limit_delay = rate_limit_delay
        self.last_request_time = 0.0
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "USBusinessDataCollector/1.0 (Public Research Project; open-data-research@example.org)"
        })

    def _throttle(self):
        """Enforces rate limiting between requests to respect open API boundaries."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self.last_request_time = time.time()

    def get_metadata(self) -> Dict[str, Any]:
        return {
            "source_name": self.name,
            "source_type": self.source_type,
            "base_url": self.base_url,
            "rate_limit_delay": self.rate_limit_delay,
            "publicly_accessible": True,
            "authentication_required": False
        }

    @abstractmethod
    def search(
        self,
        company_name: Optional[str] = None,
        industry: Optional[str] = None,
        state: Optional[str] = None,
        city: Optional[str] = None,
        zip_code: Optional[str] = None,
        naics_code: Optional[str] = None,
        sic_code: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Executes search against open source and returns raw items with metadata.
        Each returned dictionary must include:
        {
            "raw": <raw dict>,
            "source_url": <str>,
            "source_record_id": <str>,
            "fields_available": list[str],
            "collection_method": "API" | "BULK_DOWNLOAD" | "WEB"
        }
        """
        pass

    @abstractmethod
    def map_to_standard_company(self, raw_item: Dict[str, Any]) -> Dict[str, Any]:
        """Converts raw source record into standardized company JSON structure."""
        pass
