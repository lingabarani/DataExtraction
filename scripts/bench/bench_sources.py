"""
Benchmark harness for DataExtraction sources and ingestion pipeline.
Measures:
  1. Google Maps deep place run on fixtures (requests/sec, stubs/sec, wall time)
  2. Safe website crawl on local test server (requests/sec, pages/sec, wall time)
  3. Database upsert of 10,000 rows (rows/sec, wall time)
Saves results to JSON.
"""

import argparse
import asyncio
import json
import os
import pathlib
import sys
import time
from typing import Any, Dict
import httpx

os.environ.setdefault("REVIEWER_HASH_SALT", "bench-test-salt")
os.environ.setdefault("SSRF_ALLOWED_PORTS", "80,443,8080,8000")

# Resolve project root
ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
GMAPS_SRC = ROOT / "packages" / "scrapers" / "google_maps" / "src"
if str(GMAPS_SRC) not in sys.path:
    sys.path.insert(0, str(GMAPS_SRC))

from packages.scrapers.google_maps.deep_place import DeepPlaceExtractor
from gmaps_scraper.website.crawler import SafeWebsiteCrawler
from gmaps_scraper.website.extractor import WebsiteExtractor


# ---------------------------------------------------------------------------
# 1. GMaps Deep Place Benchmark (Fixture-based)
# ---------------------------------------------------------------------------

class FakeResp:
    def __init__(self, text="", status_code=200, url="https://www.google.com/x"):
        self.text = text
        self.status_code = status_code
        self.url = url
        self.headers = {}


class MockGmapsAsyncHttp:
    """Async HTTP client returning Google Maps responses without external network."""
    def __init__(self):
        self.request_count = 0
        p = [None] * 210
        p[4] = [0] * 9
        p[4][7], p[4][8] = 4.8, 150
        p[30] = "America/New_York"
        p[67] = 1
        p[100] = [None, [["g1", "Services", [
            ["a1", "In-home care", [None, [[True, "In-home care"]]]],
            ["a2", "24/7 care", [None, [[True, "24/7 care"]]]],
        ]]]]
        p[203] = [[["Monday", 1, None, [["9 AM-5 PM"]]], ["Sunday", 7, None, [["Closed"]]]]]
        wrapped_p = [None] * 14 + [p]
        self._details_body = ")]}'\n" + json.dumps([[None, [None, wrapped_p]]])

        revs = []
        for i in range(10):
            rev = [None] * 40
            rev[1] = 5
            rev[2] = ["1 month ago", None, 1700000000000]
            rev[3] = [f"Reviewer {i}", "https://avatar", f"https://contrib/{i}"]
            rev[5] = f"rev-{i}"
            rev[26] = "en"
            rev[27] = f"Excellent in-home care service provided by caregiver {i}."
            rev[34] = 2
            revs.append(rev)
        container = [None, None, revs, None, None, None, None]
        self._reviews_body = ")]}'\n" + json.dumps([None, [None] * 10 + [container]])

    async def get(self, url: str, **kwargs) -> FakeResp:
        self.request_count += 1
        is_reviews = "listugcposts" in url
        body = self._reviews_body if is_reviews else self._details_body
        return FakeResp(text=body, status_code=200, url=url)


def bench_gmaps_deep_place(num_stubs: int = 50) -> Dict[str, Any]:
    mock_http = MockGmapsAsyncHttp()
    extractor = DeepPlaceExtractor(mock_http, run_id="bench_run_01", max_reviews=10)

    stubs = [
        {
            "cid": f"1000000{i:04d}",
            "ftid": f"0x8856a:0x{i:04x}",
            "place_id": f"charlotte_care_{i:04d}",
            "name": f"Charlotte In-Home Care Agency {i}",
            "latitude": 35.2271 + (i * 0.001),
            "longitude": -80.8431 + (i * 0.001),
            "phone": f"+1704555{i:04d}",
            "website": f"https://careagency{i}.example.com",
            "address": f"{100 + i} S Tryon St, Charlotte, NC 28202",
            "category": "home care agency",
            "company_id": f"gmaps_1000000{i:04d}",
        }
        for i in range(num_stubs)
    ]

    async def _run():
        bundles = []
        for stub in stubs:
            bundle = await extractor.extract_place(stub)
            bundles.append(bundle)
        return bundles

    t0 = time.perf_counter()
    bundles = asyncio.run(_run())
    elapsed = time.perf_counter() - t0

    reqs_per_sec = mock_http.request_count / elapsed if elapsed > 0 else 0.0
    stubs_per_sec = len(bundles) / elapsed if elapsed > 0 else 0.0

    return {
        "num_stubs": num_stubs,
        "total_requests": mock_http.request_count,
        "wall_time_seconds": round(elapsed, 4),
        "requests_per_second": round(reqs_per_sec, 2),
        "stubs_per_second": round(stubs_per_sec, 2),
    }


# ---------------------------------------------------------------------------
# 2. Local Website Crawl Benchmark
# ---------------------------------------------------------------------------

PAGES_STORE = {
    "http://charlotte-senior-care.org": """
        <!DOCTYPE html>
        <html>
        <head><title>Charlotte Senior Living & Care</title></head>
        <body>
            <h1>Welcome to Charlotte Senior Care</h1>
            <p>Contact us: (704) 555-0199 or info@charlotteseniorcare.org</p>
            <nav>
                <a href="http://charlotte-senior-care.org/about">About Us</a>
                <a href="http://charlotte-senior-care.org/team">Leadership Team</a>
                <a href="http://charlotte-senior-care.org/services">Services</a>
                <a href="http://charlotte-senior-care.org/contact">Contact</a>
            </nav>
        </body>
        </html>
    """,
    "http://charlotte-senior-care.org/about": """
        <html><body>
            <h1>About Us</h1>
            <p>Licensed home care agency serving Mecklenburg and Union counties.</p>
        </body></html>
    """,
    "http://charlotte-senior-care.org/team": """
        <html><body>
            <h1>Our Leadership</h1>
            <div class="team-member">
                <h3>Dr. Sarah Jenkins</h3>
                <p>Executive Director & Administrator</p>
                <p>sarah.jenkins@charlotteseniorcare.org</p>
            </div>
            <div class="team-member">
                <h3>Marcus Vance, RN</h3>
                <p>Director of Nursing</p>
                <p>marcus.vance@charlotteseniorcare.org</p>
            </div>
        </body></html>
    """,
    "http://charlotte-senior-care.org/services": """
        <html><body>
            <h1>Elderly Care Services</h1>
            <ul>
                <li>Personal Care & Companionship</li>
                <li>24/7 Skilled Nursing</li>
                <li>Memory Care & Respite Support</li>
            </ul>
        </body></html>
    """,
    "http://charlotte-senior-care.org/contact": """
        <html><body>
            <h1>Contact Charlotte Senior Care</h1>
            <p>Address: 400 South Tryon St, Charlotte, NC 28285</p>
            <p>Phone: 704-555-0199</p>
            <p>Email: care@charlotteseniorcare.org</p>
        </body></html>
    """,
}


class MockTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url_str = str(request.url).rstrip("/")
        # Try direct match or root
        content = PAGES_STORE.get(url_str) or PAGES_STORE.get(str(request.url))
        if content is None:
            content = PAGES_STORE["http://charlotte-senior-care.org"]
        return httpx.Response(
            status_code=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            content=content.encode("utf-8"),
            request=request,
        )


def bench_website_crawl(num_iterations: int = 10) -> Dict[str, Any]:
    base_url = "http://charlotte-senior-care.org"

    async def _run_crawls():
        total_pages = 0
        crawler = SafeWebsiteCrawler(
            max_pages=5,
            timeout_seconds=5.0,
            check_dns=False,
        )
        transport = MockTransport()
        async with httpx.AsyncClient(transport=transport) as client:
            for _ in range(num_iterations):
                pages = await crawler.crawl(base_url, http_client=client)
                total_pages += len(pages)
                extractor = WebsiteExtractor()
                extractor.extract({"name": "Charlotte Senior Care", "website": base_url}, pages)
        return total_pages

    t0 = time.perf_counter()
    total_pages = asyncio.run(_run_crawls())
    elapsed = time.perf_counter() - t0

    pages_per_sec = total_pages / elapsed if elapsed > 0 else 0.0

    return {
        "num_crawls": num_iterations,
        "total_pages_crawled": total_pages,
        "wall_time_seconds": round(elapsed, 4),
        "pages_per_second": round(pages_per_sec, 2),
    }


# ---------------------------------------------------------------------------
# 3. Database Upsert Benchmark (10k rows)
# ---------------------------------------------------------------------------

def bench_db_upsert_10k() -> Dict[str, Any]:
    """Measures batch upsert of 10,000 organization entities into an optimized SQLite WAL table."""
    import sqlite3
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS test_organizations (
            id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            category TEXT,
            address TEXT,
            phone TEXT,
            website TEXT,
            domain TEXT,
            quality_score REAL,
            updated_at REAL
        );
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_test_org_norm ON test_organizations(normalized_name, domain);")
    conn.commit()

    rows = [
        (
            f"org_{i:06d}",
            f"Healthcare & Home Care Facility {i}",
            f"healthcare & home care facility {i}",
            "home care agency",
            f"{i} Pineville-Matthews Rd, Charlotte, NC 28226",
            f"+1704555{i % 10000:04d}",
            f"https://agency{i}.org",
            f"agency{i}.org",
            0.95,
            time.time(),
        )
        for i in range(10000)
    ]

    t0 = time.perf_counter()
    with conn:
        conn.executemany("""
            INSERT INTO test_organizations (id, canonical_name, normalized_name, category, address, phone, website, domain, quality_score, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                canonical_name = excluded.canonical_name,
                normalized_name = excluded.normalized_name,
                quality_score = excluded.quality_score,
                updated_at = excluded.updated_at;
        """, rows)
    elapsed = time.perf_counter() - t0

    conn.close()
    try:
        os.remove(db_path)
    except OSError:
        pass

    rows_per_sec = len(rows) / elapsed if elapsed > 0 else 0.0

    return {
        "num_rows": len(rows),
        "wall_time_seconds": round(elapsed, 4),
        "rows_per_second": round(rows_per_sec, 2),
    }


from packages.discovery.orchestrator import DiscoveryOrchestrator
from packages.discovery.sources.cms_care_compare import CMSCareCompareSource
from packages.discovery.sources.state_registry import StateRegistrySource


def bench_discovery_engine() -> Dict[str, Any]:
    """Measures end-to-end multi-source query planning, resolution, and citation."""
    sources = [CMSCareCompareSource(), StateRegistrySource()]
    orchestrator = DiscoveryOrchestrator(sources=sources)

    t0 = time.perf_counter()
    answer = asyncio.run(orchestrator.search("elderly care, home care in Charlotte metro area", budget_seconds=10.0))
    elapsed = time.perf_counter() - t0

    return {
        "wall_time_seconds": round(elapsed, 4),
        "total_organizations": answer.total_organizations,
        "total_people": answer.total_people,
        "total_cards": len(answer.cards),
        "total_citations": len(answer.citations),
        "cards_per_second": round(len(answer.cards) / elapsed, 2) if elapsed > 0 else 0,
    }


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------

def run_benchmark(output_path: str | None = None) -> Dict[str, Any]:
    print("=" * 60)
    print("Running Source & Ingestion Baseline Benchmarks")
    print("=" * 60)

    print("\n1. Measuring Google Maps deep place extraction on fixtures (50 stubs)...")
    gmaps_metrics = bench_gmaps_deep_place(num_stubs=50)
    print(f"   -> {gmaps_metrics['requests_per_second']} reqs/sec ({gmaps_metrics['wall_time_seconds']}s wall time)")

    print("\n2. Measuring Safe Website Crawler on local test server (10 runs x 5 pages)...")
    crawl_metrics = bench_website_crawl(num_iterations=10)
    print(f"   -> {crawl_metrics['pages_per_second']} pages/sec ({crawl_metrics['wall_time_seconds']}s wall time)")

    print("\n3. Measuring Database 10k batch upsert...")
    db_metrics = bench_db_upsert_10k()
    print(f"   -> {db_metrics['rows_per_second']} rows/sec ({db_metrics['wall_time_seconds']}s wall time)")

    print("\n4. Measuring Discovery Multi-Source Engine End-to-End Search...")
    discovery_metrics = bench_discovery_engine()
    print(f"   -> {discovery_metrics['cards_per_second']} cards/sec ({discovery_metrics['wall_time_seconds']}s wall time, {discovery_metrics['total_cards']} cards, {discovery_metrics['total_citations']} citations)")

    baseline = {
        "timestamp": time.time(),
        "gmaps_deep_place": gmaps_metrics,
        "website_crawl": crawl_metrics,
        "db_upsert_10k": db_metrics,
        "discovery_engine": discovery_metrics,
    }

    if output_path:
        out = pathlib.Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(baseline, f, indent=2)
        print(f"\nSaved benchmark baseline to: {output_path}")

    return baseline


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run ingestion benchmarks")
    parser.add_argument("--output", default="scripts/bench/baseline.json", help="Path to output JSON")
    args = parser.parse_args()
    run_benchmark(args.output)
