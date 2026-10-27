"""
US B2B Source Registry — defines all data sources, their metadata, and connector mappings.
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class USSourceConfig:
    key: str
    name: str
    connector_class: str
    base_url: str
    requires_key: bool = False
    api_key_env: Optional[str] = None
    rate_limit_rps: float = 2.0
    max_records: Optional[int] = None
    enabled: bool = True
    provides_executives: bool = False
    priority: int = 1  # 1=highest
    description: str = ""


US_SOURCES: List[USSourceConfig] = [
    USSourceConfig(
        key="SAM_GOV",
        name="SAM.gov Entity Registry",
        connector_class="SamGovClient",
        base_url="https://api.sam.gov/entity-information/v3",
        requires_key=False,
        rate_limit_rps=1.0,
        priority=1,
        provides_executives=True,
        description="US Federal Vendor Registry. 700K+ active vendors with EIN, NAICS, address, phone, website, and Point of Contact name/email/title.",
    ),
    USSourceConfig(
        key="SEC_EDGAR",
        name="SEC EDGAR Company Filings",
        connector_class="EdgarClient",
        base_url="https://data.sec.gov",
        requires_key=False,
        rate_limit_rps=5.0,
        priority=2,
        provides_executives=True,
        description="SEC EDGAR full company submissions. Public company legal names, CIK, SIC, address, and Named Executive Officers from 10-K/DEF 14A filings.",
    ),
    USSourceConfig(
        key="PROPUBLICA_990",
        name="ProPublica IRS 990 Nonprofit Explorer",
        connector_class="ProPublica990Client",
        base_url="https://projects.propublica.org/nonprofits/api/v2",
        requires_key=False,
        rate_limit_rps=3.0,
        priority=3,
        provides_executives=True,
        description="IRS 990 nonprofit filings via ProPublica. 1.5M+ nonprofits with executive names, titles, and compensation.",
    ),
    USSourceConfig(
        key="CENSUS_CBP",
        name="US Census County Business Patterns",
        connector_class="CensusCBPClient",
        base_url="https://api.census.gov/data",
        requires_key=True,
        api_key_env="CENSUS_DATA_API_KEY",
        rate_limit_rps=2.0,
        priority=4,
        provides_executives=False,
        description="6-digit NAICS industry codes, employee bands (1-4, 5-9, 10-19, 20-49, 50-99, 100-249, 250-499, 500+) by ZIP code.",
    ),
    USSourceConfig(
        key="USASPENDING",
        name="USASpending.gov Award Recipients",
        connector_class="USASpendingClient",
        base_url="https://api.usaspending.gov/api/v2",
        requires_key=False,
        rate_limit_rps=2.0,
        priority=5,
        provides_executives=False,
        description="Federal contract and grant award recipients. Company name, EIN, NAICS, city/state, award amounts.",
    ),
    USSourceConfig(
        key="OPENCORPORATES",
        name="OpenCorporates Business Registry",
        connector_class="OpenCorporatesClient",
        base_url="https://api.opencorporates.com/v0.4",
        requires_key=False,
        rate_limit_rps=1.0,
        priority=6,
        provides_executives=True,
        description="50-state US business registrations. Company name, state, registration date, status, and officer names.",
    ),
]

# Lookup by key
_source_map = {s.key: s for s in US_SOURCES}


def get_source_config(key: str) -> Optional[USSourceConfig]:
    return _source_map.get(key)


def get_enabled_sources() -> List[USSourceConfig]:
    return [s for s in US_SOURCES if s.enabled]


def get_executive_sources() -> List[USSourceConfig]:
    return [s for s in US_SOURCES if s.enabled and s.provides_executives]
