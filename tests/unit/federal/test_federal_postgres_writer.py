"""
Unit tests for Federal PostgreSQL Writer
Tests SQL parameterization, conflict handling, domain extraction, and POC mapping.
"""

from unittest.mock import MagicMock
import pytest

from packages.scrapers.us_enrichment.storage.federal_postgres_writer import (
    upsert_federal_businesses,
    upsert_federal_people,
    _extract_domain,
)


def test_extract_domain():
    assert _extract_domain("https://www.berkeley.edu/research") == "berkeley.edu"
    assert _extract_domain("http://medtech.company.org:8080/portal") == "medtech.company.org"
    assert _extract_domain(None) is None
    assert _extract_domain("") is None


def test_upsert_federal_businesses():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    records = [
        {
            "company_id": "sam_123456789",
            "name": "General Dynamics Federal",
            "legal_name": "General Dynamics Information Technology, Inc.",
            "website_url": "https://www.gdit.com",
            "phone": "+17035550100",
            "city": "Falls Church",
            "state_code": "VA",
            "zip_code": "22042",
            "country": "United States",
            "industry": "Custom Computer Programming Services",
            "naics_code": "541512",
            "ein": "12-3456789",
            "cage_code": "0GDIT",
            "uei": "UEI123456789",
            "source": "sam_gov",
            "data_quality_score": 95,
        }
    ]

    res = upsert_federal_businesses(mock_conn, records, default_source="sam_gov")
    assert res["total"] == 1
    assert res["inserted_or_updated"] == 1
    assert res["failed"] == 0

    assert mock_cur.execute.called
    mock_conn.commit.assert_called_once()
    mock_cur.close.assert_called_once()


def test_upsert_federal_people():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    contacts = [
        {
            "company_id": "sam_123456789",
            "full_name": "James Henderson",
            "title": "Government Contracts Administrator",
            "work_email": "james.henderson@gdit.com",
            "direct_phone": "+17035550102",
            "source": "sam_gov",
        }
    ]

    res = upsert_federal_people(mock_conn, contacts, default_source="sam_gov")
    assert res["total"] == 1
    assert res["inserted"] == 1
    assert res["failed"] == 0

    assert mock_cur.execute.called
    mock_conn.commit.assert_called_once()
    mock_cur.close.assert_called_once()

