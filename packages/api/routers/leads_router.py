"""
OneExtraction — Leads Router
Endpoints:
  GET /api/leads        — Paginated, filtered lead search
  GET /api/leads/count  — Accurate / fast count estimates
  GET /api/leads/{id}   — Single lead detail by ID
"""

import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.deps import UserPrincipal, get_current_user
from db_connector import get_connection, release_connection

logger = logging.getLogger("oneextraction.leads")

router = APIRouter(tags=["leads"])

ALLOWED_TABLES = {"us_leads", "mexico_leads"}


def _row_to_dict(row, cols: list[str], table: str) -> dict:
    """Converts a database row into a structured dictionary with parsed JSONB."""
    d = dict(zip(cols, row))
    for field in ("person", "company", "contact"):
        val = d.get(field)
        if isinstance(val, str):
            try:
                d[field] = json.loads(val)
            except Exception:
                pass
    d["table"] = table
    return d


def _clean_str(val) -> Optional[str]:
    if val is not None and isinstance(val, str) and val.strip():
        return val.strip()
    return None

def _clean_int(val) -> Optional[int]:
    if val is not None and isinstance(val, int):
        return val
    return None

def _build_where(
    table: str,
    q: Optional[str],
    nl_query: Optional[str],
    seniority: Optional[str],
    industry: Optional[str],
    state_code: Optional[str],
    email_status: Optional[str],
    api_source: Optional[str],
    country: Optional[str],
    min_score: Optional[int],
) -> tuple[str, list]:
    """Constructs parameterized WHERE clause."""
    clauses: list[str] = []
    params: list = []

    q_val = _clean_str(q)
    nl_val = _clean_str(nl_query)
    sen_val = _clean_str(seniority)
    ind_val = _clean_str(industry)
    st_val = _clean_str(state_code)
    email_val = _clean_str(email_status)
    src_val = _clean_str(api_source)
    cntry_val = _clean_str(country)
    score_val = _clean_int(min_score)

    # Keyword search across name, company, email
    if q_val:
        clauses.append('("full_name" ILIKE %s OR "company_name" ILIKE %s OR "email" ILIKE %s)')
        like = f"%{q_val}%"
        params.extend([like, like, like])

    # Natural language query keywords
    if nl_val and not q_val:
        clauses.append(
            '("full_name" ILIKE %s OR "company_name" ILIKE %s OR '
            '"industry" ILIKE %s OR "title" ILIKE %s OR "email" ILIKE %s)'
        )
        like = f"%{nl_val}%"
        params.extend([like, like, like, like, like])

    if sen_val:
        clauses.append('"seniority_level" = %s')
        params.append(sen_val)

    if ind_val:
        clauses.append('"industry" ILIKE %s')
        params.append(f"%{ind_val}%")

    if st_val:
        if table == "mexico_leads":
            clauses.append('"state" ILIKE %s')
            params.append(f"%{st_val}%")
        else:
            clauses.append('"state_code" = %s')
            params.append(st_val)

    if email_val:
        if email_val.upper() in ("VERIFIED", "DELIVERABLE_OR_CONFIRMED"):
            clauses.append('("email_status" IN (\'DELIVERABLE\', \'MX_CONFIRMED\', \'VERIFIED\'))')
        else:
            clauses.append('"email_status" = %s')
            params.append(email_val.upper())

    if src_val:
        clauses.append('"api_source" = %s')
        params.append(src_val)

    if cntry_val:
        clauses.append('"country" ILIKE %s')
        params.append(f"%{cntry_val}%")

    if score_val is not None:
        clauses.append('"lead_score" >= %s')
        params.append(score_val)

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


def _estimate_filtered_rows(cur, table: str, where: str, params: list) -> int:
    """
    Uses PostgreSQL EXPLAIN to quickly estimate filtered row counts when
    exact counts would require full-table sequential scans.
    """
    try:
        cur.execute(f'EXPLAIN SELECT 1 FROM "{table}" {where}', params)
        first_line = cur.fetchone()[0]
        # Example output: "Bitmap Heap Scan on us_leads  (cost=... rows=12400 width=4)"
        m = re.search(r"rows=(\d+)", first_line)
        if m:
            return int(m.group(1))
    except Exception as e:
        logger.warning("EXPLAIN count estimation error: %s", e)
    return 100000


# ── GET /leads ────────────────────────────────────────────────────────────────

@router.get("/leads")
def list_leads(
    table: str = Query("us_leads"),
    q: Optional[str] = Query(None),
    nl_query: Optional[str] = Query(None),
    seniority: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    state_code: Optional[str] = Query(None),
    email_status: Optional[str] = Query(None),
    api_source: Optional[str] = Query(None),
    country: Optional[str] = Query(None),
    min_score: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    user: UserPrincipal = Depends(get_current_user),
):
    """
    Returns paginated lead records with filtering and verified contact scoring.
    """
    if table not in ALLOWED_TABLES:
        raise HTTPException(status_code=400, detail=f"Invalid table: {table}. Must be one of {ALLOWED_TABLES}")

    where, params = _build_where(
        table, q, nl_query, seniority, industry,
        state_code, email_status, api_source, country, min_score
    )
    page_num = page if isinstance(page, int) and page >= 1 else 1
    limit_num = limit if isinstance(limit, int) and limit >= 1 else 50
    offset = (page_num - 1) * limit_num

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '10s'")

        # 1. Total count resolution
        if not where:
            # Instant total using pg_class statistics for unfiltered queries
            cur.execute("SELECT reltuples::BIGINT FROM pg_class WHERE relname = %s", (table,))
            row = cur.fetchone()
            total = int(row[0]) if row and row[0] > 0 else 0
        else:
            # Filtered queries: count up to 100,000
            cur.execute(
                f'SELECT COUNT(1) FROM (SELECT 1 FROM "{table}" {where} LIMIT 100001) t',
                params
            )
            capped_total = cur.fetchone()[0]
            if capped_total > 100000:
                # Fast EXPLAIN estimate rather than falsified full-table reltuples count
                total = _estimate_filtered_rows(cur, table, where, params)
            else:
                total = capped_total

        # 2. Paginated data fetch
        cur.execute(
            f'SELECT * FROM "{table}" {where} '
            f'ORDER BY "lead_score" DESC NULLS LAST '
            f'LIMIT %s OFFSET %s',
            params + [limit_num, offset]
        )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()

    except Exception as e:
        logger.error("Query error in list_leads: %s", e)
        if not conn.closed:
            conn.rollback()
        cols, rows, total = [], [], 0
    finally:
        try:
            if not conn.closed:
                cur.execute("RESET statement_timeout")
        except Exception:
            pass
        cur.close()
        release_connection(conn)

    leads = [_row_to_dict(row, cols, table) for row in rows]
    return {
        "data": leads,
        "total": total,
        "page": page_num,
        "limit": limit_num,
    }


# ── GET /leads/count ──────────────────────────────────────────────────────────

@router.get("/leads/count")
def count_leads(
    table: str = Query("us_leads"),
    seniority: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    state_code: Optional[str] = Query(None),
    email_status: Optional[str] = Query(None),
    api_source: Optional[str] = Query(None),
    user: UserPrincipal = Depends(get_current_user),
):
    """Returns total matching lead count with statement timeout protection."""
    if table not in ALLOWED_TABLES:
        raise HTTPException(status_code=400, detail=f"Invalid table: {table}")

    where, params = _build_where(
        table, None, None, seniority, industry,
        state_code, email_status, api_source, None, None
    )

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SET statement_timeout = '8s'")
        if not where:
            cur.execute("SELECT reltuples::BIGINT FROM pg_class WHERE relname = %s", (table,))
            row = cur.fetchone()
            total = int(row[0]) if row and row[0] > 0 else 0
        else:
            cur.execute(f'SELECT COUNT(1) FROM "{table}" {where}', params)
            total = cur.fetchone()[0]
    except Exception as e:
        logger.error("Error in count_leads: %s", e)
        total = 0
    finally:
        cur.close()
        release_connection(conn)

    return {"total": total}


# ── GET /leads/{id} ───────────────────────────────────────────────────────────

@router.get("/leads/{lead_id}")
def get_lead_by_id(
    lead_id: str,
    table: str = Query("us_leads"),
    user: UserPrincipal = Depends(get_current_user),
):
    """Fetches a single lead record by unique ID."""
    if table not in ALLOWED_TABLES:
        raise HTTPException(status_code=400, detail=f"Invalid table: {table}")

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(f'SELECT * FROM "{table}" WHERE "id" = %s', (lead_id.strip(),))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found in {table}")
        cols = [d[0] for d in cur.description]
        return _row_to_dict(row, cols, table)
    finally:
        cur.close()
        release_connection(conn)
