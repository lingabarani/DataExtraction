"""
Unit tests for Google Maps PostgreSQL Writer
Tests domain extraction, quality scoring, and SQL batch parameterization.
"""

import json
from unittest.mock import MagicMock
import pytest

from packages.scrapers.google_maps.postgres_writer import (
    extract_domain_from_url,
    calculate_gmaps_quality_score,
    upsert_gmaps_places_to_postgres,
    upsert_gmaps_people_to_postgres,
)


def test_extract_domain_from_url():
    assert extract_domain_from_url("https://www.example.com/about") == "example.com"
    assert extract_domain_from_url("http://sub.company.org/path?q=1") == "sub.company.org"
    assert extract_domain_from_url("clinic.healthcare.net") == "clinic.healthcare.net"
    assert extract_domain_from_url(None) is None
    assert extract_domain_from_url("null") is None
    assert extract_domain_from_url("") is None


def test_calculate_gmaps_quality_score():
    complete_place = {
        "name": "Acme Health",
        "latitude": 37.77,
        "longitude": -122.41,
        "phone": "+14155551234",
        "website": "https://acmehealth.com",
        "address": "123 Market St",
        "city": "San Francisco",
        "region": "CA",
        "category": "healthcare",
    }
    score = calculate_gmaps_quality_score(complete_place)
    assert score == 100

    minimal_place = {"name": "Basic Store"}
    assert calculate_gmaps_quality_score(minimal_place) == 20


def test_upsert_gmaps_places_to_postgres():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    places = [
        {
            "cid": "1234567890",
            "name": "Pacific Dental",
            "website": "https://pacificdental.com",
            "phone_e164": "+14155550000",
            "city": "San Francisco",
            "region": "California",
            "country_code": "US",
            "postal_code": "94105",
            "latitude": 37.78,
            "longitude": -122.40,
            "category": "dentist",
            "emails": ["info@pacificdental.com"],
        }
    ]

    res = upsert_gmaps_places_to_postgres(mock_conn, places)
    assert res["total"] == 1
    assert res["inserted_or_updated"] == 1
    assert res["failed"] == 0

    assert mock_cur.execute.called
    mock_conn.commit.assert_called_once()
    mock_cur.close.assert_called_once()


def test_upsert_gmaps_people_to_postgres():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    people = [
        {
            "company_id": "gmaps_1234567890",
            "full_name": "Dr. Sarah Connor",
            "title": "Lead Orthodontist",
            "work_email": "sarah@pacificdental.com",
            "direct_phone": "+14155550001",
        }
    ]

    res = upsert_gmaps_people_to_postgres(mock_conn, people)
    assert res["total"] == 1
    assert res["inserted"] == 1
    assert res["failed"] == 0

    assert mock_cur.execute.called
    mock_conn.commit.assert_called_once()
    mock_cur.close.assert_called_once()

