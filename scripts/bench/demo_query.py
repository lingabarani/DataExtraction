"""
Demo acceptance script for Discovery Engine.
Runs query through the real DiscoveryOrchestrator and prints per-source status and multi-source fusion.
Does not construct fake records; prints honest statuses and factual results.
"""

from __future__ import annotations

import asyncio
import logging
from packages.discovery.orchestrator import DiscoveryOrchestrator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


async def main():
    orchestrator = DiscoveryOrchestrator()
    query = "elderly care, home care in Charlotte metro area"
    print(f"Executing query: '{query}'")

    answer = await orchestrator.search(query, budget_seconds=15.0)

    print("\n" + "=" * 60)
    print("DISCOVERY ENGINE RUN REPORT")
    print("=" * 60)
    print(f"Total Organizations : {answer.total_organizations}")
    print(f"Total People        : {answer.total_people}")
    print(f"Total Citations     : {len(answer.citations)}")
    print(f"Elapsed Time        : {answer.elapsed_ms} ms")

    print("\n" + "-" * 60)
    print("PER-SOURCE EXECUTION STATUSES:")
    print("-" * 60)
    for st in answer.source_statuses:
        status_info = f"{st.status.upper()} (records: {st.record_count})"
        if st.error_message:
            status_info += f" - reason: {st.error_message}"
        print(f"  * {st.name.ljust(22)} : {status_info}")

    print("\n" + "-" * 60)
    print("SYNTHESIS MARKDOWN:")
    print("-" * 60)
    print(answer.summary_markdown)

    if answer.cards:
        print("\n" + "-" * 60)
        print(f"ORGANIZATION RESULT CARDS (Top {min(4, len(answer.cards))}):")
        print("-" * 60)
        for i, card in enumerate(answer.cards[:4], 1):
            print(f"\n[{i}] {card.name}")
            print(f"    Category      : {card.category}")
            addr = card.address or {}
            print(f"    Address       : {addr.get('street', '')}, {addr.get('city', '')}, {addr.get('state', '')} {addr.get('postal_code', '')}")
            print(f"    Phone         : {card.phone}")
            if card.cms_star_rating:
                print(f"    CMS Rating    : {card.cms_star_rating}★ ({card.cms_ownership})")
            if card.nc_license_number:
                print(f"    NC License    : {card.nc_license_number} ({card.nc_license_status})")
            print(f"    Citation IDs  : {card.citation_ids}")
            if card.named_people:
                print("    Key Personnel :")
                for p in card.named_people:
                    print(f"      * {p['name']} - {p.get('title')} [{p.get('role_type')}]")


if __name__ == "__main__":
    asyncio.run(main())
