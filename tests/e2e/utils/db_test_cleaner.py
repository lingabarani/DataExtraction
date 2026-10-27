"""
DataExtraction — E2E Test Database Harness & Cleaner
Provides hermetic test database initialization, schema provisioning,
and teardown for end-to-end integration test suites.
"""

import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Bootstrap package paths
_REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKAGES = _REPO_ROOT / "packages"

for p in [_PACKAGES / "infrastructure", _PACKAGES / "pipeline", _REPO_ROOT]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


class EphemeralDatabaseHarness:
    """
    Creates an isolated SQLite or PostgreSQL test database schema,
    pre-loads core tables, and resets state between scenarios.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or ":memory:"
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._provision_schema()

    def _provision_schema(self):
        """Provisions schema mimicking the OneExtraction/DataExtraction production layout."""
        cur = self.conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS companies (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                legal_name TEXT,
                trade_name TEXT,
                normalized_name TEXT,
                entity_type TEXT,
                website TEXT,
                domain TEXT,
                email TEXT,
                phone TEXT,
                phones TEXT DEFAULT '[]',
                emails TEXT DEFAULT '[]',
                industry TEXT,
                naics_code TEXT,
                sic_code TEXT,
                ein TEXT,
                rfc TEXT,
                cik TEXT,
                npi TEXT,
                cage_code TEXT,
                uei TEXT,
                state_of_incorporation TEXT,
                street TEXT,
                city TEXT,
                state TEXT,
                state_code TEXT,
                zip_code TEXT,
                country TEXT DEFAULT 'United States',
                latitude REAL,
                longitude REAL,
                source_count INTEGER DEFAULT 1,
                source_records TEXT DEFAULT '[]',
                data_quality_score INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                deduplicated_at TIMESTAMP,
                normalized_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS people (
                id TEXT PRIMARY KEY,
                company_id TEXT,
                first_name TEXT,
                last_name TEXT,
                full_name TEXT,
                title TEXT,
                normalized_title TEXT,
                email TEXT,
                phone TEXT,
                linkedin_url TEXT,
                career_history TEXT DEFAULT '[]',
                source_records TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS us_leads (
                id TEXT PRIMARY KEY,
                company_id TEXT NOT NULL,
                company_name TEXT NOT NULL,
                domain TEXT,
                state_code TEXT,
                industry TEXT,
                lead_score INTEGER DEFAULT 0,
                lead_status TEXT DEFAULT 'NEW',
                company JSON,
                person JSON,
                contact JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS mexico_leads (
                id TEXT PRIMARY KEY,
                company_id TEXT NOT NULL,
                company_name TEXT NOT NULL,
                rfc TEXT,
                domain TEXT,
                state_code TEXT,
                lead_score INTEGER DEFAULT 0,
                lead_status TEXT DEFAULT 'NEW',
                company JSON,
                person JSON,
                contact JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS dead_letter_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                source_name TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                raw_payload TEXT,
                error_reason TEXT,
                error_traceback TEXT,
                status TEXT DEFAULT 'PENDING',
                retry_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_retried_at TIMESTAMP,
                resolved_at TIMESTAMP
            );
        """)
        self.conn.commit()
        cur.close()

    def get_connection(self):
        """Returns connection instance."""
        return self.conn

    def clean_tables(self):
        """Truncates all tables for a pristine test state."""
        cur = self.conn.cursor()
        for tbl in ["companies", "people", "us_leads", "mexico_leads", "dead_letter_queue"]:
            cur.execute(f"DELETE FROM {tbl};")
        self.conn.commit()
        cur.close()

    def close(self):
        """Closes connection."""
        if self.conn:
            self.conn.close()

