"""
Unit tests for scripts/migration/import_linkedin_folder.py
Tests offline deduplication, provenance classification, and data normalization.
"""

from __future__ import annotations

import pathlib
import sqlite3
import tempfile
import pytest

from scripts.migration.import_linkedin_folder import (
    deduplicate_entities,
    load_seed_names,
    read_lead_intel_db,
    read_liscraper_db,
)


@pytest.fixture
def temp_linkedin_env():
    """Create a temporary mock LinkedIn folder structure."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = pathlib.Path(tmp_dir)
        scratch_dir = root / "scratch"
        scratch_dir.mkdir(parents=True, exist_ok=True)
        data_dir = root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        backend_dir = root / "backend"
        backend_dir.mkdir(parents=True, exist_ok=True)

        # 1. Mock seed script
        seed_file = scratch_dir / "seed_tamilnadu_ceos.py"
        seed_file.write_text(
            """
LEADS = [
    {"full_name": "Ramesh Kumar", "company": "Tech Solutions"},
    {"full_name": "Priya Sharma", "company": "CloudWave"}
]
""",
            encoding="utf-8",
        )

        # 2. Mock liscraper.db
        liscraper_path = data_dir / "liscraper.db"
        conn = sqlite3.connect(liscraper_path)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE companies (
                id INTEGER PRIMARY KEY,
                name TEXT,
                slug TEXT,
                domain TEXT,
                website TEXT,
                industry TEXT,
                description TEXT,
                employee_count TEXT,
                logo TEXT,
                address TEXT
            )
        """
        )
        cur.execute(
            """
            CREATE TABLE people (
                id INTEGER PRIMARY KEY,
                name TEXT,
                slug TEXT,
                headline TEXT,
                about TEXT,
                company TEXT,
                company_slug TEXT,
                company_domain TEXT,
                city TEXT,
                region TEXT,
                country TEXT,
                emails TEXT,
                phones TEXT,
                raw_public TEXT,
                raw_voyager TEXT,
                source TEXT,
                email_confidence REAL,
                status TEXT
            )
        """
        )
        cur.execute(
            """
            INSERT INTO companies (name, slug, domain, website)
            VALUES ('Tech Solutions', 'tech-solutions', 'techsolutions.com', 'https://techsolutions.com')
        """
        )
        cur.execute(
            """
            INSERT INTO people (name, slug, headline, company, country, emails)
            VALUES ('Ramesh Kumar', 'ramesh-kumar', 'CEO at Tech Solutions', 'Tech Solutions', 'India', '["ramesh.kumar@techsolutions.com"]')
        """
        )
        cur.execute(
            """
            INSERT INTO people (name, slug, headline, company, country, emails)
            VALUES ('John Doe', 'john-doe', 'Founder at Alpha Labs', 'Alpha Labs', 'USA', '["john@alphalabs.com"]')
        """
        )
        conn.commit()
        conn.close()

        # 3. Mock lead_intel.db
        lead_intel_path = backend_dir / "lead_intel.db"
        conn2 = sqlite3.connect(lead_intel_path)
        cur2 = conn2.cursor()
        cur2.execute(
            """
            CREATE TABLE companies (
                id INTEGER PRIMARY KEY,
                name TEXT,
                domain TEXT,
                website TEXT,
                industry TEXT,
                employee_count TEXT,
                linkedin_url TEXT,
                city TEXT,
                state TEXT,
                country TEXT
            )
        """
        )
        cur2.execute(
            """
            CREATE TABLE contacts (
                id INTEGER PRIMARY KEY,
                company_id INTEGER,
                first_name TEXT,
                last_name TEXT,
                full_name TEXT,
                title TEXT,
                department TEXT,
                confidence_score REAL,
                linkedin_url TEXT,
                source TEXT
            )
        """
        )
        cur2.execute(
            """
            CREATE TABLE contact_emails (
                id INTEGER PRIMARY KEY,
                contact_id INTEGER,
                email TEXT,
                email_type TEXT,
                verification_status TEXT,
                confidence_score REAL
            )
        """
        )
        cur2.execute(
            """
            CREATE TABLE contact_phones (
                id INTEGER PRIMARY KEY,
                contact_id INTEGER,
                phone TEXT,
                phone_type TEXT,
                is_valid INTEGER
            )
        """
        )
        # Duplicate company
        cur2.execute(
            """
            INSERT INTO companies (id, name, domain, website, city, state, country)
            VALUES (1, 'Tech Solutions Inc', 'techsolutions.com', 'https://techsolutions.com', 'Chennai', 'TN', 'India')
        """
        )
        # New company
        cur2.execute(
            """
            INSERT INTO companies (id, name, domain, website, city, state, country)
            VALUES (2, 'Beta Health', 'betahealth.org', 'https://betahealth.org', 'Charlotte', 'NC', 'USA')
        """
        )
        # Duplicate person: Ramesh Kumar
        cur2.execute(
            """
            INSERT INTO contacts (id, company_id, first_name, last_name, full_name, title, linkedin_url)
            VALUES (1, 1, 'Ramesh', 'Kumar', 'Ramesh Kumar', 'Chief Executive Officer', 'https://linkedin.com/in/ramesh-kumar')
        """
        )
        cur2.execute(
            """
            INSERT INTO contact_emails (contact_id, email, email_type, verification_status, confidence_score)
            VALUES (1, 'ramesh.kumar@techsolutions.com', 'inferred', 'unverified', 0.8)
        """
        )
        # New person: Jane Smith
        cur2.execute(
            """
            INSERT INTO contacts (id, company_id, first_name, last_name, full_name, title, linkedin_url)
            VALUES (2, 2, 'Jane', 'Smith', 'Jane Smith', 'Director of Nursing', 'https://linkedin.com/in/jane-smith')
        """
        )
        conn2.commit()
        conn2.close()

        yield root


def test_load_seed_names(temp_linkedin_env):
    seeds = load_seed_names(temp_linkedin_env)
    assert "ramesh kumar" in seeds
    assert "priya sharma" in seeds
    assert len(seeds) == 2


def test_read_dbs_and_provenance(temp_linkedin_env):
    seeds = load_seed_names(temp_linkedin_env)

    # 1. Read liscraper
    lis_people, lis_companies = read_liscraper_db(temp_linkedin_env / "data" / "liscraper.db", seeds)
    assert len(lis_people) == 2
    assert len(lis_companies) == 1

    # Check that Ramesh Kumar is marked manual_seed because of scratch/ file
    ramesh_lis = next(p for p in lis_people if p["normalized_name"] == "ramesh kumar")
    assert ramesh_lis["provenance"] == "manual_seed"
    assert ramesh_lis["verified"] is False

    # Check that John Doe is marked legacy_import
    john_lis = next(p for p in lis_people if p["normalized_name"] == "john doe")
    assert john_lis["provenance"] == "legacy_import"

    # 2. Read lead_intel
    li_people, li_companies = read_lead_intel_db(temp_linkedin_env / "backend" / "lead_intel.db", seeds)
    assert len(li_people) == 2
    assert len(li_companies) == 2

    # 3. Deduplicate across stores
    all_people = lis_people + li_people
    all_companies = lis_companies + li_companies

    deduped_people, deduped_companies = deduplicate_entities(all_people, all_companies)

    # People: Ramesh Kumar appeared in both, John Doe in liscraper, Jane Smith in lead_intel -> Total 3 unique
    assert len(deduped_people) == 3

    # Companies: Tech Solutions appeared in both (same domain), Beta Health in lead_intel -> Total 2 unique
    assert len(deduped_companies) == 2

    # Verify Ramesh Kumar preserved manual_seed and merged emails
    ramesh_dedup = next(p for p in deduped_people if p["normalized_name"] == "ramesh kumar")
    assert ramesh_dedup["provenance"] == "manual_seed"
    assert ramesh_dedup["verified"] is False
    assert len(ramesh_dedup["emails"]) == 1
    assert ramesh_dedup["emails"][0]["value"] == "ramesh.kumar@techsolutions.com"
    # Verify email labels are 'inferred'
    for email_entry in ramesh_dedup["emails"]:
        assert email_entry["label"] == "inferred"
