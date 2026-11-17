"""
Unit tests for packages/scrapers/linkedin.
Tests:
  - Public profile ld+json parsing on real trimmed fixtures
  - Company ld+json parsing on Microsoft fixture
  - LinkedIn HTTP client status translation and circuit breaker
  - Key Vault integration for LinkedIn credentials
  - Authenticated mode disabled by default
"""

import json
import pathlib
import pytest

from packages.scrapers.linkedin.client import (
    Blocked,
    LinkedInHttpClient,
)
from packages.scrapers.linkedin.company import parse_public_company
from packages.scrapers.linkedin.public_profile import parse_public_profile
from packages.infrastructure.key_vault import KeyRecord, set_secrets_manager

FIXTURES_DIR = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "linkedin"


# ---------------------------------------------------------------------------
# 1. Profile Parsing Tests against Real Fixtures
# ---------------------------------------------------------------------------

def test_parse_public_profile_satya_nadella():
    fixture_path = FIXTURES_DIR / "profile_1.html"
    assert fixture_path.exists(), f"Missing fixture {fixture_path}"
    html = fixture_path.read_text(encoding="utf-8")
    data = parse_public_profile(html)

    assert data["name"] == "Satya Nadella"
    assert "Microsoft" in (data["headline"] or "")
    assert data["company"] == "Microsoft"
    assert "https://www.linkedin.com/company/microsoft" in (data["company_url"] or "")
    assert data["country"] in ("United States", "US")


def test_parse_public_profile_bill_gates():
    fixture_path = FIXTURES_DIR / "profile_2.html"
    assert fixture_path.exists(), f"Missing fixture {fixture_path}"
    html = fixture_path.read_text(encoding="utf-8")
    data = parse_public_profile(html)

    assert data["name"] == "Bill Gates"
    assert "Gates Foundation" in (data["headline"] or "") or "Co-chair" in (data["headline"] or "")
    assert data["country"] in ("United States", "US")


def test_parse_public_profile_jeff_weiner():
    fixture_path = FIXTURES_DIR / "profile_3.html"
    assert fixture_path.exists(), f"Missing fixture {fixture_path}"
    html = fixture_path.read_text(encoding="utf-8")
    data = parse_public_profile(html)

    assert data["name"] == "Jeff Weiner"
    assert data["country"] in ("United States", "US")


# ---------------------------------------------------------------------------
# 2. Company Parsing Tests against Real Fixture
# ---------------------------------------------------------------------------

def test_parse_public_company_microsoft():
    fixture_path = FIXTURES_DIR / "company_1.html"
    assert fixture_path.exists(), f"Missing fixture {fixture_path}"
    html = fixture_path.read_text(encoding="utf-8")
    data = parse_public_company(html)

    assert data["name"] == "Microsoft"
    assert data["slug"] == "microsoft"
    assert "linkedin.com/company/microsoft" in (data["website"] or "").lower()
    assert data["address"] is not None
    assert data["address"].get("city") == "Redmond"
    assert data["address"].get("region") in ("Washington", "WA")


# ---------------------------------------------------------------------------
# 3. HTTP Client and Circuit Breaker Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_client_circuit_breaker_and_error_translation():
    client = LinkedInHttpClient(breaker_window=4, breaker_threshold=0.5, max_attempts=1)

    # Record 999 responses to trip breaker
    client._record_status(999)
    client._record_status(999)
    assert client.is_breaker_tripped() is True

    # Breaker tripped should immediately raise Blocked without making outbound request
    with pytest.raises(Blocked):
        await client.get_public_page("https://www.linkedin.com/in/test")


def test_authenticated_mode_disabled_by_default(monkeypatch):
    monkeypatch.delenv("LINKEDIN_AUTH_ENABLED", raising=False)
    client = LinkedInHttpClient()
    assert client.is_auth_enabled() is False
    assert client.get_auth_cookies() is None


def test_key_vault_cookie_integration(monkeypatch):
    monkeypatch.setenv("LINKEDIN_AUTH_ENABLED", "true")

    class FakeSecretsManager:
        def get_active_key(self, provider: str):
            if provider == "linkedin":
                return KeyRecord(
                    id="rec-1",
                    provider="linkedin",
                    value=json.dumps({"li_at": "test_li_at_token", "jsessionid": "ajax:999"}),
                )
            return None

    set_secrets_manager(FakeSecretsManager())
    client = LinkedInHttpClient()
    cookies = client.get_auth_cookies()

    assert cookies is not None
    assert cookies["li_at"] == "test_li_at_token"
    assert cookies["jsessionid"] == "ajax:999"
    set_secrets_manager(None)
