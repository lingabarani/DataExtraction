"""
Guard test against fabricated / hardcoded business records and mock data in production code.
Must fail before R1 fixes and pass after.
"""

import ast
from pathlib import Path
import re
import pytest
import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FORBIDDEN_KEYS = {"phone", "administrator", "license_number", "facility_name", "provider_name"}
FORBIDDEN_STRINGS = ["CHARLOTTE_CMS_REFERENCE", "NC_DHSR_CHARLOTTE_REGISTRY"]
PHONE_REGEX = re.compile(r"\(\d{3}\) \d{3}-\d{4}")


def test_no_hardcoded_business_records_ast():
    """Scan packages/ and scripts/ for module-level lists/dicts with >= 3 entries with business keys."""
    violations = []

    for folder in ["packages", "scripts"]:
        root_dir = PROJECT_ROOT / folder
        for py_path in root_dir.rglob("*.py"):
            # Skip test files or fixtures if any exist in scripts/
            if "tests" in py_path.parts or "test_" in py_path.name:
                continue

            try:
                tree = ast.parse(py_path.read_text(encoding="utf-8", errors="replace"), filename=str(py_path))
            except Exception:
                continue

            for node in tree.body:
                # Check top-level assignments: x = [...] or x = {...}
                if isinstance(node, ast.Assign):
                    target_val = node.value
                    if isinstance(target_val, (ast.List, ast.Tuple)):
                        matching_entries = 0
                        for elt in target_val.elts:
                            if isinstance(elt, ast.Dict):
                                keys = {k.value for k in elt.keys if isinstance(k, ast.Constant)}
                                if keys.intersection(FORBIDDEN_KEYS):
                                    matching_entries += 1
                        if matching_entries >= 3:
                            targets = [getattr(t, "id", str(t)) for t in node.targets]
                            violations.append(f"{py_path.relative_to(PROJECT_ROOT)}: assign {targets} has {matching_entries} hardcoded business dicts")

    assert not violations, "Found hardcoded business records in code:\n" + "\n".join(violations)


def test_no_forbidden_strings_or_phone_literals():
    """Fail if any source module contains forbidden reference names or US phone literals."""
    sources_dir = PROJECT_ROOT / "packages" / "discovery" / "sources"
    violations = []

    for py_path in sources_dir.glob("*.py"):
        content = py_path.read_text(encoding="utf-8", errors="replace")
        for s in FORBIDDEN_STRINGS:
            if s in content:
                violations.append(f"{py_path.name} contains forbidden string '{s}'")
        phone_matches = PHONE_REGEX.findall(content)
        if phone_matches:
            violations.append(f"{py_path.name} contains phone literals: {phone_matches[:3]}")

    assert not violations, "Found forbidden strings/phones in sources:\n" + "\n".join(violations)


@pytest.mark.anyio
async def test_sources_return_zero_and_honest_status_when_network_blocked(monkeypatch):
    """Run each source adapter with network calls blocked; assert 0 orgs and honest status."""
    from packages.discovery.http import _CLIENTS
    _CLIENTS.clear()

    from packages.discovery.models import SearchIntent, Budget
    from packages.discovery.sources.cms_care_compare import CMSCareCompareSource
    from packages.discovery.sources.state_registry import StateRegistrySource
    from packages.discovery.sources.google_maps import GoogleMapsSource
    from packages.discovery.sources.web_search import WebSearchSource
    from packages.discovery.sources.website_crawl import WebsiteCrawlSource
    from packages.discovery.sources.linkedin_public import LinkedInPublicSource

    class BlockedTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise httpx.ConnectError("Network is completely disabled in test")

    orig_async_client = httpx.AsyncClient

    def blocked_client_factory(*args, **kwargs):
        kwargs["transport"] = BlockedTransport()
        return orig_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", blocked_client_factory)

    intent = SearchIntent(query="elderly care in Charlotte NC", categories=["home care"], want=["organizations"])
    budget = Budget(total_seconds=5.0)

    sources = [
        CMSCareCompareSource(),
        StateRegistrySource(),
        GoogleMapsSource(),
        WebSearchSource(),
        WebsiteCrawlSource(),
        LinkedInPublicSource(),
    ]

    for src in sources:
        orgs = []
        statuses = []
        async for res in src.search(intent, budget):
            if res.organizations:
                orgs.extend(res.organizations)
            elif res.record:
                orgs.append(res.record)
            if res.status:
                statuses.append(res.status.status)

        assert len(orgs) == 0, f"Source {src.name} returned {len(orgs)} organizations when network blocked: {[o.name for o in orgs]}"
        for st in statuses:
            assert st in {"unavailable", "error", "empty", "blocked"}, f"Source {src.name} gave invalid status {st}"
