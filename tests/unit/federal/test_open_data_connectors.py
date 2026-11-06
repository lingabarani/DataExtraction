"""
Unit tests for all 8 US Federal & Open Data Connectors.
Verifies API key loading, request parameterization, and response parsing.
"""

from unittest.mock import MagicMock, patch
import pytest

from packages.scrapers.us_enrichment.config.settings import settings
from packages.scrapers.us_enrichment.connectors.census_client import CensusClient
from packages.scrapers.us_enrichment.connectors.datagov_client import DataGovClient
from packages.scrapers.us_enrichment.connectors.bls_client import BLSClient
from packages.scrapers.us_enrichment.connectors.openfda_client import OpenFDAClient
from packages.scrapers.us_enrichment.connectors.bea_client import BEAClient
from packages.scrapers.us_enrichment.connectors.eia_client import EIAClient
from packages.scrapers.us_enrichment.connectors.usgs_client import USGSClient
from packages.scrapers.us_enrichment.connectors.sam_client import SamGovClient


def test_api_keys_loaded_in_settings():
    """Verifies that all 8 API keys are successfully loaded from environment / settings."""
    assert settings.CENSUS_DATA_API_KEY == "cb6683ac6176d2a4a41bca4f45c6b78e8c7387da"
    assert settings.DATA_GOV_API_KEY == "dWqhICx4uOPUbUvySbaAqoR1kJBFsah73yUkEYkw"
    assert settings.BLS_API_KEY == "ddeaff94eb0c444897b6e41af7aead1a"
    assert settings.OPENFDA_API_KEY == "AX6Nh9Xb6krpzg9phodb6ogZ9aq2WzAzqjkgV2sd"
    assert settings.BEA_DATA_API_KEY == "240FF73B-E43E-48B0-ACBF-1876ACF8C51A"
    assert settings.EIA_API_KEY == "ItCVOdtJMSdwLGY2leDJH3U8s3LU4N1JxaJBK77A"
    assert settings.USGS_WATER_API_KEY == "AXr8mTNpL6xIkSPiVRXWR4KHM61JSXb7Er6I03dY"
    assert settings.SAM_GOV_API_KEY == "SAM-40645f36-37cf-4acc-8551-13c452896c05"


def test_census_client_parsing():
    client = CensusClient()
    assert client.api_key == settings.CENSUS_DATA_API_KEY

    mock_matrix = [
        ["ESTAB", "EMP", "PAYANN", "NAICS2017", "NAME", "state"],
        ["1420", "28500", "1542000", "541511", "California", "06"],
    ]
    with patch.object(client, "get_data", return_value=mock_matrix):
        records = client.get_county_business_patterns(year="2022", state="06", naics="541511")
        assert len(records) == 1
        rec = records[0]
        assert rec["state_name"] == "California"
        assert rec["establishment_count"] == 1420
        assert rec["employee_count"] == 28500
        assert rec["source"] == "census_cbp"


def test_openfda_client_parsing():
    client = OpenFDAClient()
    assert client.api_key == settings.OPENFDA_API_KEY

    mock_payload = {
        "results": [
            {
                "registration": {
                    "registration_number": "1234567",
                    "name": "MedTech Bio Corp",
                    "city": "Irvine",
                    "state_code": "CA",
                    "postal_code": "92618",
                    "owner_operator": {"owner_operator_name": "MedTech Global Holdings"},
                }
            }
        ]
    }
    with patch.object(client, "get_data", return_value=mock_payload):
        establishments = client.get_device_establishments(limit=1)
        assert len(establishments) == 1
        est = establishments[0]
        assert est["company_id"] == "fda_1234567"
        assert est["name"] == "MedTech Global Holdings"
        assert est["city"] == "Irvine"
        assert est["state_code"] == "CA"
        assert est["source"] == "openfda"


def test_bls_client_parsing():
    client = BLSClient()
    assert client.api_key == settings.BLS_API_KEY

    mock_resp = {
        "Results": {
            "series": [
                {
                    "seriesID": "CEU0000000001",
                    "data": [
                        {"year": "2023", "period": "M01", "periodName": "January", "value": "155000"}
                    ],
                }
            ]
        }
    }
    with patch.object(client, "get_data", return_value=mock_resp):
        series = client.get_industry_employment_series(["CEU0000000001"])
        assert len(series) == 1
        assert series[0]["series_id"] == "CEU0000000001"
        assert series[0]["value"] == 155000.0


def test_bea_client_parsing():
    client = BEAClient()
    assert client.api_key == settings.BEA_DATA_API_KEY

    mock_resp = {
        "BEAAPI": {
            "Results": {
                "Data": [
                    {
                        "GeoFips": "06000",
                        "GeoName": "California",
                        "Description": "All industry total",
                        "DataValue": "3800000",
                        "TimePeriod": "2023",
                        "CL_UNIT": "Millions of current dollars",
                    }
                ]
            }
        }
    }
    with patch.object(client, "get_data", return_value=mock_resp):
        rows = client.get_regional_gdp_by_industry()
        assert len(rows) == 1
        assert rows[0]["geo_name"] == "California"
        assert rows[0]["gdp_value"] == "3800000"


def test_eia_client_parsing():
    client = EIAClient()
    assert client.api_key == settings.EIA_API_KEY

    mock_resp = {
        "response": {
            "data": [
                {
                    "stateid": "TX",
                    "stateDescription": "Texas",
                    "sectorDescription": "commercial",
                    "period": "2024-01",
                    "price": "9.45",
                    "revenue": "540000",
                    "sales": "57000",
                }
            ]
        }
    }
    with patch.object(client, "get_data", return_value=mock_resp):
        providers = client.get_commercial_electricity_providers(state="TX")
        assert len(providers) == 1
        assert providers[0]["state"] == "TX"
        assert providers[0]["price_cents_per_kwh"] == 9.45


def test_usgs_client_parsing():
    client = USGSClient()
    mock_resp = {
        "value": {
            "timeSeries": [
                {
                    "sourceInfo": {
                        "siteName": "COLORADO RIVER AT AUSTIN, TX",
                        "siteCode": [{"value": "08158000"}],
                        "geoLocation": {
                            "geogLocation": {"latitude": 30.25, "longitude": -97.74}
                        },
                    }
                }
            ]
        }
    }
    with patch.object(client, "get_data", return_value=mock_resp):
        facilities = client.get_monitoring_facilities("TX")
        assert len(facilities) == 1
        assert facilities[0]["company_id"] == "usgs_site_08158000"
        assert facilities[0]["name"] == "COLORADO RIVER AT AUSTIN, TX"
        assert facilities[0]["latitude"] == 30.25


def test_datagov_client_parsing():
    client = DataGovClient()
    assert client.api_key == settings.DATA_GOV_API_KEY

    mock_resp = {
        "results": [
            {
                "id": 110635,
                "school.name": "University of California-Berkeley",
                "school.city": "Berkeley",
                "school.state": "CA",
                "school.zip": "94720",
                "school.school_url": "www.berkeley.edu",
            }
        ]
    }
    with patch.object(client, "get_data", return_value=mock_resp):
        institutions = client.get_educational_institutions(state="CA")
        assert len(institutions) == 1
        inst = institutions[0]
        assert inst["company_id"] == "ed_inst_110635"
        assert inst["name"] == "University of California-Berkeley"
        assert inst["city"] == "Berkeley"
        assert inst["website_url"] == "www.berkeley.edu"


def test_sam_client_api_key_initialization():
    client = SamGovClient()
    assert client.api_key == settings.SAM_GOV_API_KEY

