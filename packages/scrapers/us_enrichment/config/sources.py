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
    USSourceConfig(
        key="OPENFDA",
        name="openFDA Drug & Device Registrations",
        connector_class="OpenFDAClient",
        base_url="https://api.fda.gov",
        requires_key=True,
        api_key_env="OPENFDA_API_KEY",
        rate_limit_rps=4.0,
        priority=7,
        provides_executives=False,
        description="Regulated life sciences, medical device, and pharmaceutical establishment registrations.",
    ),
    USSourceConfig(
        key="BLS",
        name="Bureau of Labor Statistics",
        connector_class="BLSClient",
        base_url="https://api.bls.gov/publicAPI/v2",
        requires_key=True,
        api_key_env="BLS_API_KEY",
        rate_limit_rps=2.0,
        priority=8,
        provides_executives=False,
        description="QCEW and Occupational Employment and Wages statistics by NAICS and county.",
    ),
    USSourceConfig(
        key="BEA",
        name="Bureau of Economic Analysis",
        connector_class="BEAClient",
        base_url="https://apps.bea.gov/api/data",
        requires_key=True,
        api_key_env="BEA_DATA_API_KEY",
        rate_limit_rps=2.0,
        priority=9,
        provides_executives=False,
        description="Regional economic accounts and GDP by industry output metrics.",
    ),
    USSourceConfig(
        key="EIA",
        name="Energy Information Administration",
        connector_class="EIAClient",
        base_url="https://api.eia.gov/v2",
        requires_key=True,
        api_key_env="EIA_API_KEY",
        rate_limit_rps=3.0,
        priority=10,
        provides_executives=False,
        description="Commercial energy consumers, utilities, and power generation facilities.",
    ),
    USSourceConfig(
        key="USGS",
        name="USGS Water Resources",
        connector_class="USGSClient",
        base_url="https://waterservices.usgs.gov/nwis",
        requires_key=False,
        api_key_env="USGS_WATER_API_KEY",
        rate_limit_rps=2.0,
        priority=11,
        provides_executives=False,
        description="Water resource facilities, monitoring stations, and utility entities.",
    ),
    USSourceConfig(
        key="DATA_GOV",
        name="Data.gov Federal Open Catalog",
        connector_class="DataGovClient",
        base_url="https://api.data.gov",
        requires_key=True,
        api_key_env="DATA_GOV_API_KEY",
        rate_limit_rps=3.0,
        priority=12,
        provides_executives=False,
        description="Federal cross-agency open datasets and educational scorecards.",
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
