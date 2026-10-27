"""
US B2B Connectors package.
Provides unified access to all 6 US open-data source clients.
"""

from .sam_client import SamGovClient, sam_gov_client
from .edgar_client import EdgarClient, edgar_client
from .propublica990_client import ProPublica990Client, propublica_client
from .cbp_client import CensusCBPClient, census_cbp_client
from .usaspending_client import USASpendingClient, usaspending_client
from .opencorporates_client import OpenCorporatesClient, opencorporates_client
from .npi_client import NPIClient, npi_client
from .fcc_uls_client import FCCULSClient, fcc_uls_client
from .opendirectories_client import OpenDirectoriesClient, opendirectories_client

_CONNECTOR_MAP = {
    "SAM_GOV": sam_gov_client,
    "SEC_EDGAR": edgar_client,
    "PROPUBLICA_990": propublica_client,
    "CENSUS_CBP": census_cbp_client,
    "USASPENDING": usaspending_client,
    "OPENCORPORATES": opencorporates_client,
    "CMS_NPI": npi_client,
    "FCC_ULS": fcc_uls_client,
    "OPENDIRECTORIES": opendirectories_client,
}


def get_connector(source_key: str):
    """Returns the singleton connector for a given source key."""
    return _CONNECTOR_MAP.get(source_key)


__all__ = [
    "SamGovClient", "sam_gov_client",
    "EdgarClient", "edgar_client",
    "ProPublica990Client", "propublica_client",
    "CensusCBPClient", "census_cbp_client",
    "USASpendingClient", "usaspending_client",
    "OpenCorporatesClient", "opencorporates_client",
    "NPIClient", "npi_client",
    "FCCULSClient", "fcc_uls_client",
    "OpenDirectoriesClient", "opendirectories_client",
    "get_connector",
]


