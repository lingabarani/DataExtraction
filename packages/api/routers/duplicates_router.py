"""
OneExtraction — Duplicates Router
Endpoints:
  GET  /api/duplicates/analyse   — Group counts & sample duplicate records
  POST /api/duplicates/clean     — Safe chunked removal of duplicate records
  POST /api/duplicates/clean-all — Safe multi-criteria deduplication sweep
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.deps import UserPrincipal, get_current_user
from db_connector import get_connection, release_connection

logger = logging.getLogger("oneextraction.duplicates")

router = APIRouter(tags=["duplicates"])

ALLOWED_TABLES = {"us_leads", "mexico_leads"}


# ── Request Models ─────────────────────────────────────────────────────────────

class CleanRequest(BaseModel):
    check: str
    table: str = "us_leads"


# ── Analysis Helpers ──────────────────────────────────────────────────────────

def _count_dup_email(cur, table: str) -> tuple[int, int, list]:
    cur.execute(f"""
        SELECT email, COUNT(1) AS cnt, ARRAY_AGG(DISTINCT api_source) AS srcs
        FROM "{table}"
        WHERE email IS NOT NULL AND email != ''
        GROUP BY email HAVING COUNT(1) > 1
        ORDER BY cnt DESC LIMIT 5
    """)
    rows = cur.fetchall()
    groups = len(rows)

    cur.execute(f"""
        SELECT COUNT(1) FROM (
            SELECT email FROM "{table}"
            WHERE email IS NOT NULL AND email != ''
            GROUP BY email HAVING COUNT(1) > 1
            LIMIT 5000
        ) t
    """)
    extra = cur.fetchone()[0] or 0
    sample = [
        {"value": r[0], "count": r[1], "sources": r[2] or [], "ids": []}
        for r in rows
    ]
    return groups, extra, sample


def _count_dup_phone(cur, table: str) -> tuple[int, int, list]:
    cur.execute(f"""
        SELECT phone, COUNT(1) AS cnt, ARRAY_AGG(DISTINCT api_source) AS srcs
        FROM "{table}"
        WHERE phone IS NOT NULL AND phone != ''
        GROUP BY phone HAVING COUNT(1) > 1
        ORDER BY cnt DESC LIMIT 5
    """)
    rows = cur.fetchall()
    groups = len(rows)

    cur.execute(f"""
        SELECT COUNT(1) FROM (
            SELECT phone FROM "{table}"
            WHERE phone IS NOT NULL AND phone != ''
            GROUP BY phone HAVING COUNT(1) > 1
            LIMIT 5000
        ) t
    """)
    extra = cur.fetchone()[0] or 0
    sample = [
        {"value": r[0], "count": r[1], "sources": r[2] or [], "ids": []}
        for r in rows
    ]
    return groups, extra, sample


def _count_dup_name_company(cur, table: str) -> tuple[int, int, list]:
    cur.execute(f"""
        SELECT COUNT(1) FROM (
            SELECT 1 FROM "{table}" TABLESAMPLE SYSTEM(1)
            WHERE full_name IS NOT NULL AND company_name IS NOT NULL
            GROUP BY UPPER(full_name), UPPER(company_name)
            HAVING COUNT(1) > 1
        ) t
    """)
    sample_count = cur.fetchone()[0] or 0
    estimated = sample_count * 100
    return sample_count, estimated, []


def _count_cross_source(cur, table: str) -> tuple[int, int, list]:
    cur.execute(f"""
        SELECT COUNT(1) FROM (
            SELECT 1 FROM "{table}" TABLESAMPLE SYSTEM(5)
            WHERE email IS NOT NULL AND email != ''
            GROUP BY email
            HAVING COUNT(DISTINCT api_source) > 1
        ) t
    """)
    sample_count = cur.fetchone()[0] or 0
    estimated = sample_count * 20
    return sample_count, estimated, []


# ── GET /api/duplicates/analyse ───────────────────────────────────────────────

@router.get("/duplicates/analyse")
def analyse_duplicates(user: UserPrincipal = Depends(get_current_user)):
    """Analyzes duplicate concentrations across US and Mexico lead datasets."""
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '15s'")
        results = []

        checks = [
            ("email", "Exact Email Match", _count_dup_email),
            ("phone", "Exact Phone Match", _count_dup_phone),
            ("name_company", "Name + Company Match", _count_dup_name_company),
            ("cross_source", "Cross-Source Overlap", _count_cross_source),
        ]

        for check_id, label, fn in checks:
            for tbl in ("us_leads", "mexico_leads"):
                try:
                    groups, extra, sample = fn(cur, tbl)
                except Exception as e:
                    logger.warning("Error analysing %s on %s: %s", check_id, tbl, e)
                    conn.rollback()
                    groups, extra, sample = 0, 0, []

                results.append({
                    "id": f"{tbl}_{check_id}",
                    "check": check_id,
                    "label": f"{label} ({'US' if tbl == 'us_leads' else 'Mexico'})",
                    "table": tbl,
                    "groups": groups,
                    "extra_rows": extra,
                    "sample": sample,
                })

        cur.execute('SELECT COUNT(1) FROM "us_leads"')
        us_total = cur.fetchone()[0]
        cur.execute('SELECT COUNT(1) FROM "mexico_leads"')
        mx_total = cur.fetchone()[0]

        us_dups = sum(r["extra_rows"] for r in results if r["table"] == "us_leads")
        mx_dups = sum(r["extra_rows"] for r in results if r["table"] == "mexico_leads")

        return {
            "us_total": us_total,
            "mx_total": mx_total,
            "us_duplicates": us_dups,
            "mx_duplicates": mx_dups,
            "us_unique": max(0, us_total - us_dups),
            "mx_unique": max(0, mx_total - mx_dups),
            "results": results,
            "analysed_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        try:
            if not conn.closed:
                cur.execute("RESET statement_timeout")
        except Exception:
            pass
        cur.close()
        release_connection(conn)


# ── Safe Chunked Deletion Helper ──────────────────────────────────────────────

def _delete_dups_chunked(conn, table: str, check: str, batch_size: int = 1000) -> int:
    """
    Safely deletes duplicate rows in batches to prevent long table locks and statement timeouts.
    Retains the record with highest lead_score and earliest created_at.
    """
    if check == "email":
        partition_expr = "COALESCE(LOWER(TRIM(email)), id)"
    elif check == "phone":
        partition_expr = "COALESCE(LOWER(TRIM(phone)), id)"
    elif check == "name_company":
        partition_expr = "UPPER(TRIM(COALESCE(full_name, ''))), UPPER(TRIM(COALESCE(company_name, '')))"
    elif check == "cross_source":
        partition_expr = "COALESCE(LOWER(TRIM(email)), id)"
    else:
        return 0

    total_deleted = 0
    max_batches = 10  # safety cap per request

    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '30s'")
        for _ in range(max_batches):
            # Find a batch of duplicate IDs
            cur.execute(f"""
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY {partition_expr}
                        ORDER BY lead_score DESC NULLS LAST, created_at ASC
                    ) AS rn
                    FROM "{table}"
                ) ranked
                WHERE rn > 1
                LIMIT %s
            """, (batch_size,))
            ids_to_delete = [r[0] for r in cur.fetchall()]

            if not ids_to_delete:
                break

            cur.execute(f'DELETE FROM "{table}" WHERE id = ANY(%s)', (ids_to_delete,))
            deleted = cur.rowcount
            conn.commit()
            total_deleted += deleted

            if deleted < batch_size:
                break
    except Exception as e:
        logger.error("Error during duplicate deletion (%s on %s): %s", check, table, e)
        conn.rollback()
    finally:
        cur.close()

    return total_deleted


# ── POST /api/duplicates/clean ────────────────────────────────────────────────

@router.post("/duplicates/clean")
def clean_duplicates(
    body: CleanRequest,
    user: UserPrincipal = Depends(get_current_user),
):
    """Safely cleans duplicate records for a specific check and dataset."""
    if body.table not in ALLOWED_TABLES:
        raise HTTPException(status_code=400, detail=f"Invalid table: {body.table}")

    conn = get_connection()
    try:
        removed = _delete_dups_chunked(conn, body.table, body.check)
        logger.info("Removed %d duplicates from %s for check=%s by user=%s",
                    removed, body.table, body.check, user.email)
        return {"removed": removed, "table": body.table, "check": body.check}
    finally:
        release_connection(conn)


# ── POST /api/duplicates/clean-all ────────────────────────────────────────────

@router.post("/duplicates/clean-all")
def clean_all_duplicates(user: UserPrincipal = Depends(get_current_user)):
    """Runs a multi-tier deduplication cleanup across all supported tables."""
    conn = get_connection()
    total = 0
    try:
        for tbl in ("us_leads", "mexico_leads"):
            for chk in ("email", "phone", "name_company"):
                total += _delete_dups_chunked(conn, tbl, chk)
        logger.info("Clean-all removed a total of %d duplicates by user=%s", total, user.email)
        return {"removed": total}
    finally:
        release_connection(conn)
