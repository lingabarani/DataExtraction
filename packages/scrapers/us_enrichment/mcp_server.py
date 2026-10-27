"""
OneExtraction US B2B Model Context Protocol (MCP) Server.
Exposes the OneExtraction US Business & C-Suite Executive Database natively to AI agents
(Antigravity, Claude Desktop, Hermes, ChatGPT) using standard MCP tools.
"""

import sys
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional

from .config.settings import settings
from .connectors.rdap_client import rdap_client
from .connectors.wikipedia_client import wikipedia_client


def load_scraped_companies() -> List[Dict[str, Any]]:
    """Loads canonical company JSON records from output storage."""
    target_file = settings.API_COMPANIES_DIR / "us_companies.json"
    if not target_file.exists():
        return []
    try:
        with open(target_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def load_scraped_executives() -> List[Dict[str, Any]]:
    """Loads C-suite executive JSON records from output storage."""
    target_file = settings.API_PEOPLE_DIR / "us_people.json"
    if not target_file.exists():
        return []
    try:
        with open(target_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


# ── MCP Tool Implementations ──────────────────────────────────────────────────

def search_companies_tool(query: str = "", industry: str = "", state: str = "", limit: int = 10) -> List[Dict[str, Any]]:
    """MCP Tool: Search canonical US companies by name query, industry, or state."""
    companies = load_scraped_companies()
    results = []

    q = (query or "").lower().strip()
    ind = (industry or "").lower().strip()
    st = (state or "").lower().strip()

    for c in companies:
        name = (c.get("legal_name") or c.get("trade_name") or "").lower()
        c_ind = (c.get("industry") or "").lower()
        c_st = (c.get("address", {}).get("state_code") or c.get("address", {}).get("state") or "").lower()

        match = True
        if q and q not in name:
            match = False
        if ind and ind not in c_ind:
            match = False
        if st and st != c_st:
            match = False

        if match:
            results.append(c)
            if len(results) >= limit:
                break

    return results


def get_company_details_tool(company_id: str) -> Optional[Dict[str, Any]]:
    """MCP Tool: Get full details for a company by company_id or EIN/CIK."""
    companies = load_scraped_companies()
    cid = company_id.lower().strip()

    for c in companies:
        if c.get("company_id", "").lower() == cid or c.get("ein", "") == cid or c.get("cik", "") == cid:
            # Also attach executives
            execs = get_csuite_executives_tool(c.get("company_id", ""))
            c_copy = dict(c)
            c_copy["executives"] = execs
            return c_copy

    return None


def get_csuite_executives_tool(company_id: str) -> List[Dict[str, Any]]:
    """MCP Tool: Get C-suite decision-makers linked to a company."""
    people = load_scraped_executives()
    cid = company_id.lower().strip()

    return [p for p in people if p.get("company_id", "").lower() == cid]


def enrich_domain_rdap_tool(domain: str) -> Optional[Dict[str, Any]]:
    """MCP Tool: Live ICANN RDAP WHOIS lookup for domain registrant ownership."""
    return rdap_client.fetch_domain_info(domain)


def enrich_wikipedia_summary_tool(company_name: str) -> Optional[Dict[str, Any]]:
    """MCP Tool: Fetch public corporate history summary from Wikipedia REST API."""
    return wikipedia_client.fetch_summary(company_name)


# ── MCP CLI & Stdio Server Runner ─────────────────────────────────────────────

def run_cli_test():
    """CLI test mode demonstrating native MCP tool queries."""
    print("=== OneExtraction US B2B MCP Server Interface ===")
    companies = load_scraped_companies()
    execs = load_scraped_executives()
    print(f"Loaded Database Records: {len(companies):,} Companies, {len(execs):,} Executives")

    if companies:
        sample_comp = companies[0]
        cid = sample_comp.get("company_id")
        print(f"\n[Tool Test: search_companies_tool(limit=2)]")
        search_res = search_companies_tool(limit=2)
        print(json.dumps(search_res, indent=2))

        print(f"\n[Tool Test: get_company_details_tool('{cid}')]")
        details = get_company_details_tool(cid)
        print(json.dumps(details, indent=2))
    else:
        print("No companies loaded yet. Run 'python scripts/us_bulk_ingest.py' to populate the database.")


def main():
    parser = argparse.ArgumentParser(description="OneExtraction US B2B MCP Server")
    parser.add_argument("--test", action="store_true", help="Run CLI test mode")
    parser.add_argument("--stdio", action="store_true", help="Run in stdio mode (for Kiro/Claude)")
    args = parser.parse_args()

    if args.test:
        run_cli_test()
    elif args.stdio:
        # Import and run stdio server
        try:
            from .mcp_server_stdio import MCPStdioServer
            server = MCPStdioServer()
            server.run()
        except ImportError:
            print("Error: mcp_server_stdio.py not found", file=sys.stderr)
            sys.exit(1)
    else:
        # Default: run stdio server for MCP protocol
        try:
            from .mcp_server_stdio import MCPStdioServer
            server = MCPStdioServer()
            server.run()
        except ImportError:
            print("Error: mcp_server_stdio.py not found", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
