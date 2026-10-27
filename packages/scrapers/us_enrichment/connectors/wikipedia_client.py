"""
Wikipedia Corporate Summary Connector.
Source: https://en.wikipedia.org/api/rest_v1/page/summary/{company_name}
Coverage: All major US corporations, public companies, and notable organizations.
Provides: Public Corporate History Summary, Key Industry, Description, Headquarters Info.
No API key required.
"""

import time
import requests
from typing import Dict, Any, Optional

try:
    from botasaurus.request import request as bt_request, Request as BtRequest
    HAS_BOTASAURUS = True
except ImportError:
    HAS_BOTASAURUS = False

WIKI_API_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/"

if HAS_BOTASAURUS:
    @bt_request(cache=True, parallel=4, output=None)
    def fetch_wikipedia_summary_botasaurus(request: BtRequest, title: str) -> Dict[str, Any]:
        """Botasaurus @request decorated fetcher for Wikipedia page summary."""
        clean_t = title.replace(" ", "_").strip()
        url = f"{WIKI_API_URL}{clean_t}"
        headers = {
            "User-Agent": "OneExtraction-B2B-Research/1.0",
            "Accept": "application/json",
        }
        try:
            response = request.get(url, headers=headers)
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return {}


class WikipediaClient:
    """
    Fetches corporate summaries and historical descriptions from Wikipedia REST API.
    """

    SOURCE_KEY = "WIKIPEDIA"
    SOURCE_NAME = "Wikipedia Corporate Summaries"

    def __init__(self, rate_limit_rps: float = 5.0):
        self.delay = 1.0 / rate_limit_rps
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "OneExtraction-B2B-Research/1.0",
            "Accept": "application/json",
        })

    def fetch_summary(self, company_name: str) -> Optional[Dict[str, Any]]:
        """Queries Wikipedia REST API for company overview summary."""
        clean_name = company_name.replace(" ", "_").strip()
        if not clean_name:
            return None

        if HAS_BOTASAURUS:
            try:
                res = fetch_wikipedia_summary_botasaurus(clean_name)
                if res and "extract" in res:
                    return {
                        "title": res.get("title"),
                        "summary": res.get("extract"),
                        "description": res.get("description"),
                        "url": res.get("content_urls", {}).get("desktop", {}).get("page"),
                    }
            except Exception:
                pass

        time.sleep(self.delay)
        try:
            r = self.session.get(f"{WIKI_API_URL}{clean_name}", timeout=10)
            if r.status_code == 200:
                res = r.json()
                return {
                    "title": res.get("title"),
                    "summary": res.get("extract"),
                    "description": res.get("description"),
                    "url": res.get("content_urls", {}).get("desktop", {}).get("page"),
                }
        except Exception:
            pass
        return None


wikipedia_client = WikipediaClient()
