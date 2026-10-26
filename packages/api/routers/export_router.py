"""
OneExtraction — High-Performance Streaming Export Router
Streams lead records as CSV or JSON using PostgreSQL server-side named cursors.
Eliminates memory spikes and OOM crashes even when exporting 500,000+ records.
Secured via JWT token (via Bearer header or ?token= query parameter).
"""

import csv
import io
import json
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from api.deps import UserPrincipal, get_current_user
from db_connector import get_connection, release_connection

logger = logging.getLogger("oneextraction.export")

router = APIRouter(tags=["export"])

# Whitelisted columns for export
DEFAULT_COLS = [
    "full_name", "title", "seniority_level", "email", "email_status",
    "phone", "company_name", "domain", "industry", "city", "state_code",
    "country", "lead_score", "api_source",
]

ALL_FLAT_COLS = [
    "id", "full_name", "first_name", "last_name", "title", "standardized_title",
    "seniority_level", "department", "email", "email_status", "email_confidence_score",
    "phone", "linkedin_url", "is_current", "company_id", "company_name", "domain",
    "industry", "naics_code", "ein", "cik", "employee_band", "city", "state", "state_code",
    "zip_code", "country", "person_quality_score", "company_quality_score",
    "lead_score", "api_source", "created_at", "updated_at",
]


def _clean_str(val) -> Optional[str]:
    if val is not None and isinstance(val, str) and val.strip():
        return val.strip()
    return None

def _build_where(
    table: str,
    seniority: Optional[str],
    industry: Optional[str],
    state_code: Optional[str],
    email_status: Optional[str],
    api_source: Optional[str],
) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []

    sen_val = _clean_str(seniority)
    ind_val = _clean_str(industry)
    st_val = _clean_str(state_code)
    email_val = _clean_str(email_status)
    src_val = _clean_str(api_source)

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
        clauses.append('"email_status" = %s')
        params.append(email_val.upper())
    if src_val:
        clauses.append('"api_source" = %s')
        params.append(src_val)

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


@router.get("/export/leads")
def export_leads(
    table: str = Query("us_leads"),
    format: str = Query("csv"),
    columns: Optional[str] = Query(None),
    seniority: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    state_code: Optional[str] = Query(None),
    email_status: Optional[str] = Query(None),
    api_source: Optional[str] = Query(None),
    limit: Optional[int] = Query(None, ge=1, le=1000000),
    user: UserPrincipal = Depends(get_current_user),
):
    """
    Streams filtered leads directly from the database using PostgreSQL server-side named cursors.
    Supports CSV and JSON formats.
    """
    if table not in ("us_leads", "mexico_leads"):
        raise HTTPException(status_code=400, detail="Table must be us_leads or mexico_leads")

    # Column resolution and sanitization
    if columns and isinstance(columns, str) and columns.strip():
        requested_cols = [c.strip() for c in columns.split(",")]
    else:
        requested_cols = DEFAULT_COLS
    safe_cols = [c for c in requested_cols if c in ALL_FLAT_COLS]
    if not safe_cols:
        safe_cols = DEFAULT_COLS

    where, params = _build_where(table, seniority, industry, state_code, email_status, api_source)
    col_str = ", ".join(f'"{c}"' for c in safe_cols)

    limit_clause = f"LIMIT {limit}" if limit else ""
    sql = f'SELECT {col_str} FROM "{table}" {where} ORDER BY "lead_score" DESC NULLS LAST {limit_clause}'

    cursor_name = f"export_{uuid.uuid4().hex[:12]}"
    filename = f"{table}_export"

    logger.info("Starting streaming export for user=%s table=%s format=%s", user.email, table, format)

    # ── 1. Streaming CSV (Server-Side Cursor) ──────────────────────────────────
    if format.lower() == "csv":
        def _csv_stream():
            conn = get_connection()
            cur = None
            try:
                # Named cursor forces PostgreSQL to stream rows in batches
                cur = conn.cursor(name=cursor_name)
                cur.itersize = 2000
                cur.execute(sql, params)

                buf = io.StringIO()
                writer = csv.writer(buf)

                # Write header
                writer.writerow(safe_cols)
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate()

                # Stream records in batches of 2000
                while True:
                    rows = cur.fetchmany(2000)
                    if not rows:
                        break
                    for row in rows:
                        writer.writerow([
                            "" if val is None else (json.dumps(val) if isinstance(val, (dict, list)) else str(val))
                            for val in row
                        ])
                    yield buf.getvalue()
                    buf.seek(0)
                    buf.truncate()

            except Exception as e:
                logger.error("Error during CSV stream: %s", e)
                raise e
            finally:
                if cur is not None and not cur.closed:
                    cur.close()
                release_connection(conn)

        return StreamingResponse(
            _csv_stream(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
        )

    # ── 2. Streaming JSON (Server-Side Cursor) ─────────────────────────────────
    if format.lower() == "json":
        def _json_stream():
            conn = get_connection()
            cur = None
            try:
                cur = conn.cursor(name=cursor_name)
                cur.itersize = 2000
                cur.execute(sql, params)

                yield "[\n"
                first_row = True

                while True:
                    rows = cur.fetchmany(2000)
                    if not rows:
                        break

                    chunk = []
                    for row in rows:
                        record = dict(zip(safe_cols, row))
                        record_json = json.dumps(record, default=str)
                        if not first_row:
                            chunk.append(",\n" + record_json)
                        else:
                            chunk.append(record_json)
                            first_row = False
                    yield "".join(chunk)

                yield "\n]"
            except Exception as e:
                logger.error("Error during JSON stream: %s", e)
                raise e
            finally:
                if cur is not None and not cur.closed:
                    cur.close()
                release_connection(conn)

        return StreamingResponse(
            _json_stream(),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
        )

    # ── 3. Fallback for XLSX (Safe bounded export) ─────────────────────────────
    if format.lower() == "xlsx":
        # Bounded export for XLSX to protect server memory (cap at 25,000 rows)
        conn = get_connection()
        try:
            import openpyxl
            cur = conn.cursor()
            cur.execute(sql + " LIMIT 25000", params)
            rows = cur.fetchall()
            cur.close()

            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Leads"
            ws.append(safe_cols)

            for row in rows:
                ws.append([
                    "" if val is None else (json.dumps(val) if isinstance(val, (dict, list)) else str(val))
                    for val in row
                ])

            buf = io.BytesIO()
            wb.save(buf)
            buf.seek(0)

            return StreamingResponse(
                buf,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f'attachment; filename="{filename}.xlsx"'},
            )
        except ImportError:
            # Fall back to CSV if openpyxl is not installed
            return export_leads(
                table=table, format="csv", columns=columns, seniority=seniority,
                industry=industry, state_code=state_code, email_status=email_status,
                api_source=api_source, limit=limit, user=user
            )
        finally:
            release_connection(conn)

    raise HTTPException(status_code=400, detail=f"Unsupported format: {format}. Use csv or json.")


@router.get("/export/leads/csv")
def export_leads_csv_shortcut(
    table: str = Query("us_leads"),
    user: UserPrincipal = Depends(get_current_user),
):
    """Convenience shortcut for quick full-table CSV export."""
    return export_leads(table=table, format="csv", user=user)
