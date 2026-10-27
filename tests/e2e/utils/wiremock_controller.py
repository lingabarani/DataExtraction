"""
DataExtraction — Hermetic Mock Gateway & Controller
Provides context-managed interception of third-party external HTTP calls
for government registries, Overpass mirrors, and Google Maps protobuf endpoints.
"""

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def load_fixture(fixture_name: str) -> Any:
    """Loads a JSON test fixture from tests/e2e/fixtures."""
    file_path = _FIXTURES_DIR / fixture_name
    if not file_path.exists():
        raise FileNotFoundError(f"Fixture not found: {file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


@contextmanager
def mock_all_upstream_apis():
    """
    Context manager that intercepts all external HTTP network calls
    and routes them to deterministic synthetic fixtures.
    """
    federal_fixtures = load_fixture("mock_federal_records.json")
    gmaps_fixtures = load_fixture("mock_gmaps_places.json")
    osm_fixtures = load_fixture("mock_osm_elements.json")

    with patch("httpx.AsyncClient.get") as mock_async_get, \
         patch("httpx.AsyncClient.post") as mock_async_post, \
         patch("httpx.Client.get") as mock_sync_get, \
         patch("httpx.Client.post") as mock_sync_post, \
         patch("urllib.request.urlopen") as mock_urlopen:

        # Default mock response generator
        def _make_mock_response(data: Any, status_code: int = 200):
            m = MagicMock()
            m.status_code = status_code
            m.json.return_value = data
            m.text = json.dumps(data) if isinstance(data, (dict, list)) else str(data)
            m.content = m.text.encode("utf-8")
            m.read.return_value = m.content
            return m

        mock_async_get.return_value = _make_mock_response(federal_fixtures["sec_edgar"])
        mock_sync_get.return_value = _make_mock_response(federal_fixtures["sec_edgar"])

        yield {
            "federal": federal_fixtures,
            "gmaps": gmaps_fixtures,
            "osm": osm_fixtures,
        }

