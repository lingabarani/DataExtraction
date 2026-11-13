"""
OneExtraction — Unified Database Connector with Connection Pooling
Supports PostgreSQL with high-concurrency ThreadedConnectionPool.

Usage:
    from db_connector import get_connection, release_connection, get_db_cursor

    # Option 1: Context manager (recommended - automatically returns to pool)
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT COUNT(1) FROM companies")
        print(cur.fetchone()[0])

    # Option 2: Direct connection with explicit release
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(1) FROM companies")
        ...
    finally:
        cur.close()
        release_connection(conn)
"""

import os
import re
import sys
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Generator, Tuple, Any, Dict, List

_SAFE_IDENTIFIER_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$')

def _assert_safe_identifier(identifier: str) -> str:
    if not isinstance(identifier, str) or not _SAFE_IDENTIFIER_RE.match(identifier.strip()):
        raise ValueError(f"Insecure or malformed SQL identifier: {identifier!r}")
    return identifier.strip()


from dotenv import load_dotenv

# Set up logger
logger = logging.getLogger("dataextraction.db")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [DB] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

_CURRENT_DIR = Path(__file__).resolve().parent
if str(_CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(_CURRENT_DIR))

# Resolve packages root so "packages.infrastructure" is importable
_PACKAGES_ROOT = _CURRENT_DIR.parent.parent
if str(_PACKAGES_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACKAGES_ROOT))

try:
    from packages.infrastructure.config_manager import config_manager
except ImportError:
    from config_manager import config_manager  # direct-run fallback

_db_conf = config_manager.get_database_config()
DATABASE_TYPE = _db_conf["type"]
DB_HOST = _db_conf["host"]
DB_PORT = _db_conf["port"]
DB_NAME = _db_conf["dbname"]
DB_USER = _db_conf["user"]
DB_PASS = _db_conf["password"]
DB_POOL_MIN = _db_conf["pool_min"]
DB_POOL_MAX = _db_conf["pool_max"]

# Global Threaded Connection Pool
_PG_POOL: Optional[object] = None


def _init_pool():
    """
    Initialises the PostgreSQL connection pool.
    Uses environment-aware timeouts:
      - Development/test: 2s connect timeout, 2 minimum connections (fast startup)
      - Production: configurable via POSTGRES_POOL_CONNECT_TIMEOUT (default 5s)
    """
    global _PG_POOL
    if _PG_POOL is None and DATABASE_TYPE == "postgresql":
        try:
            import psycopg2.pool
            import os
            is_dev = os.getenv("ENVIRONMENT", "development").lower() in ("development", "dev", "test")
            connect_timeout = int(os.getenv("POSTGRES_POOL_CONNECT_TIMEOUT", "2" if is_dev else "5"))
            # Use 2 minconn in dev (fast startup); higher in production via env var
            pool_min = DB_POOL_MIN if not is_dev else min(DB_POOL_MIN, 2)
            _PG_POOL = psycopg2.pool.ThreadedConnectionPool(
                minconn=pool_min,
                maxconn=DB_POOL_MAX,
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASS,
                connect_timeout=connect_timeout,
                options="-c search_path=staging_dataextraction,master_dataextraction,identity_resolution,raw_dataextraction,search_dataextraction,public",
            )
            logger.info(
                "Initialised PostgreSQL connection pool (min=%d max=%d timeout=%ds) → %s:%d/%s",
                pool_min, DB_POOL_MAX, connect_timeout, DB_HOST, DB_PORT, DB_NAME,
            )
        except Exception as e:
            logger.error("Failed to initialise PostgreSQL connection pool: %s", e)
            raise RuntimeError(f"PostgreSQL connection pool initialisation failed: {e}") from e


def get_connection(row_factory: bool = False):
    """
    Acquires a database connection from the pool.
    Caller MUST return connection using release_connection(conn) or use context managers.
    """
    if DATABASE_TYPE == "postgresql":
        if _PG_POOL is None:
            _init_pool()
        try:
            conn = _PG_POOL.getconn()
            if getattr(conn, "closed", 0) != 0:
                _PG_POOL.putconn(conn, close=True)
                conn = _PG_POOL.getconn()
            # Test-on-borrow fast ping to ensure connection is live
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                conn.commit()
            except Exception:
                try:
                    _PG_POOL.putconn(conn, close=True)
                except Exception:
                    pass
                conn = _PG_POOL.getconn()
            if getattr(conn, "autocommit", None) is not False:
                conn.autocommit = False
            return conn
        except Exception as e:
            logger.error("Error acquiring connection from pool: %s", e)
            # Direct fallback if pool is saturated
            import psycopg2
            is_dev = os.getenv("ENVIRONMENT", "development").lower() in ("development", "dev", "test")
            connect_timeout = int(os.getenv("POSTGRES_POOL_CONNECT_TIMEOUT", "2" if is_dev else "5"))
            return psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASS,
                connect_timeout=connect_timeout,
                options="-c search_path=staging_dataextraction,master_dataextraction,identity_resolution,raw_dataextraction,search_dataextraction,public",
            )
    else:
        raise RuntimeError(
            f"Unsupported DATABASE_TYPE='{DATABASE_TYPE}'. "
            "Enterprise architecture strictly enforces PostgreSQL. SQLite fallback is disabled."
        )


get_db_connection = get_connection


def execute_query(query: str, params: Optional[Tuple[Any, ...]] = None) -> List[Any]:
    """
    Executes a parameterized query safely via the pooled connection cursor.
    Returns fetched rows if available; commits and returns empty list otherwise.
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(query, params or ())
        if cur.description:
            return cur.fetchall()
        conn.commit()
        return []


def release_connection(conn) -> None:
    """Returns an acquired connection back to the pool."""
    if conn is None:
        return
    if DATABASE_TYPE == "postgresql" and _PG_POOL is not None:
        try:
            if getattr(conn, "closed", 0) != 0:
                try:
                    _PG_POOL.putconn(conn, close=True)
                except Exception:
                    pass
                return
            conn.rollback()
            _PG_POOL.putconn(conn, close=False)
        except Exception as e:
            err_msg = str(e).lower()
            if "unkeyed" in err_msg or "not in pool" in err_msg:
                try:
                    conn.close()
                except Exception:
                    pass
            else:
                logger.warning("Error releasing connection back to pool: %s", e)
                try:
                    conn.close()
                except Exception:
                    pass
    else:
        try:
            conn.close()
        except Exception:
            pass


def close_pool() -> None:
    """Cleanly closes all pooled database connections upon process termination."""
    global _PG_POOL
    if _PG_POOL is not None:
        try:
            _PG_POOL.closeall()
            logger.info("Closed PostgreSQL connection pool.")
        except Exception as e:
            logger.warning("Error closing connection pool: %s", e)
        finally:
            _PG_POOL = None


def get_db_pool_status() -> Dict[str, Any]:
    """Returns runtime connection pool status."""
    global _PG_POOL
    if _PG_POOL is not None:
        return {
            "initialized": True,
            "minconn": getattr(_PG_POOL, "minconn", 1),
            "maxconn": getattr(_PG_POOL, "maxconn", 10),
            "closed": getattr(_PG_POOL, "closed", False),
        }
    return {"initialized": False, "status": "uninitialized"}


# Standard aliases
close_connection_pool = close_pool
_release_connection = release_connection



@contextmanager
def get_db_connection() -> Generator[object, None, None]:
    """
    Context manager for database connections.
    Automatically handles commit/rollback and releases connection back to pool.
    """
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        if hasattr(conn, "rollback") and not conn.closed:
            conn.rollback()
        raise e
    finally:
        release_connection(conn)


@contextmanager
def get_db_cursor(dict_cursor: bool = False) -> Generator[Tuple[object, object], None, None]:
    """
    Context manager yielding (connection, cursor).
    Closes cursor and returns connection to pool cleanly upon completion.
    """
    conn = get_connection()
    cur = None
    try:
        if dict_cursor and DATABASE_TYPE == "postgresql":
            from psycopg2.extras import RealDictCursor
            cur = conn.cursor(cursor_factory=RealDictCursor)
        else:
            cur = conn.cursor()
        yield conn, cur
        conn.commit()
    except Exception as e:
        if hasattr(conn, "rollback") and not conn.closed:
            conn.rollback()
        raise e
    finally:
        if cur is not None and not cur.closed:
            cur.close()
        release_connection(conn)


def get_cursor(conn, dict_cursor: bool = False):
    """Returns a cursor from an existing connection."""
    if DATABASE_TYPE == "postgresql" and dict_cursor:
        from psycopg2.extras import RealDictCursor
        return conn.cursor(cursor_factory=RealDictCursor)
    return conn.cursor()


def placeholder() -> str:
    """Returns SQL parameter placeholder: %s (Postgres standard)."""
    return "%s"


def db_info() -> str:
    """Returns a human-readable connection description."""
    return f"PostgreSQL {DB_HOST}:{DB_PORT}/{DB_NAME}"


# ── Upsert helpers ────────────────────────────────────────────────────────────

def upsert_company(conn, record: dict) -> str:
    """
    Inserts a new company or updates existing record by ID.
    Returns the company ID.
    Never overwrites existing non-null fields with empty/null values.
    """
    rid = record.get("id")
    if not rid:
        raise ValueError("Record must have an 'id' before upsert")

    data = {k: v for k, v in record.items() if v is not None and v != "" and v != "[]"}
    data["id"] = rid

    cols = [_assert_safe_identifier(c) for c in data.keys()]
    values = [data[c] for c in cols]
    ph = ", ".join(["%s"] * len(cols))
    col_str = ", ".join(f'"{c}"' for c in cols)

    update_cols = [c for c in cols if c not in ("id", "created_at")]
    if update_cols:
        update_str = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
        sql = f"""
            INSERT INTO companies ({col_str})
            VALUES ({ph})
            ON CONFLICT (id) DO UPDATE SET {update_str}, updated_at = NOW()
        """
    else:
        sql = f"""
            INSERT INTO companies ({col_str})
            VALUES ({ph})
            ON CONFLICT (id) DO NOTHING
        """

    cur = conn.cursor()
    try:
        cur.execute(sql, values)
    finally:
        cur.close()
    return rid


def upsert_person(conn, record: dict) -> str:
    """
    Inserts a new person or updates existing record by ID.
    Returns the person ID.
    """
    rid = record.get("id")
    if not rid:
        raise ValueError("Record must have an 'id' before upsert")

    data = {k: v for k, v in record.items() if v is not None and v != "" and v != "[]"}
    data["id"] = rid

    cols = [_assert_safe_identifier(c) for c in data.keys()]
    values = [data[c] for c in cols]
    ph = ", ".join(["%s"] * len(cols))
    col_str = ", ".join(f'"{c}"' for c in cols)

    update_cols = [c for c in cols if c not in ("id", "created_at")]
    if update_cols:
        update_str = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
        sql = f"""
            INSERT INTO people ({col_str})
            VALUES ({ph})
            ON CONFLICT (id) DO UPDATE SET {update_str}, updated_at = NOW()
        """
    else:
        sql = f"""
            INSERT INTO people ({col_str})
            VALUES ({ph})
            ON CONFLICT (id) DO NOTHING
        """

    cur = conn.cursor()
    try:
        cur.execute(sql, values)
    finally:
        cur.close()
    return rid


def update_company_fields(conn, company_id: str, updates: dict) -> None:
    """Patch specific non-null fields on an existing company row."""
    if not updates:
        return
    fields = [_assert_safe_identifier(k) for k in updates if k not in ("id", "created_at") and updates[k] is not None]
    if not fields:
        return
    set_str = ", ".join(f'"{f}" = %s' for f in fields)
    values = [updates[f] for f in fields] + [company_id]
    cur = conn.cursor()
    try:
        cur.execute(f"UPDATE companies SET {set_str}, updated_at = NOW() WHERE id = %s", values)
    finally:
        cur.close()


def update_person_fields(conn, person_id: str, updates: dict) -> None:
    """Patch specific non-null fields on an existing person row."""
    if not updates:
        return
    fields = [_assert_safe_identifier(k) for k in updates if k not in ("id", "created_at") and updates[k] is not None]
    if not fields:
        return
    set_str = ", ".join(f'"{f}" = %s' for f in fields)
    values = [updates[f] for f in fields] + [person_id]
    cur = conn.cursor()
    try:
        cur.execute(f"UPDATE people SET {set_str}, updated_at = NOW() WHERE id = %s", values)
    finally:
        cur.close()


def sync_company_geometry(conn, company_id: str, latitude: float, longitude: float) -> bool:
    """
    Synchronizes spatial geometry (Point 4326) and numeric coordinates.
    Gracefully falls back to numeric coordinates if PostGIS is not available.
    """
    if not company_id or latitude is None or longitude is None:
        return False
    try:
        lat = float(latitude)
        lon = float(longitude)
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return False
    except (ValueError, TypeError):
        return False

    cur = conn.cursor()
    try:
        if DATABASE_TYPE == "postgresql":
            try:
                cur.execute("""
                    UPDATE companies
                    SET latitude = %s,
                        longitude = %s,
                        geom = ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                        updated_at = NOW()
                    WHERE id = %s
                """, (lat, lon, lon, lat, company_id))
                return True
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                cur.execute("""
                    UPDATE companies
                    SET latitude = %s,
                        longitude = %s,
                        updated_at = NOW()
                    WHERE id = %s
                """, (lat, lon, company_id))
                return True
        else:
            cur.execute("UPDATE companies SET latitude = ?, longitude = ? WHERE id = ?",
                        (lat, lon, company_id))
            return True
    finally:
        cur.close()


def find_nearby_companies(conn, latitude: float, longitude: float, radius_km: float = 10.0, limit: int = 50) -> list:
    """
    Finds companies within radius_km distance using PostGIS ST_DWithin
    or Haversine formula fallback.
    """
    try:
        lat = float(latitude)
        lon = float(longitude)
        rad = float(radius_km)
        lim = int(limit)
    except (ValueError, TypeError):
        return []

    cur = get_cursor(conn, dict_cursor=True)
    try:
        if DATABASE_TYPE == "postgresql":
            try:
                # 1. PostGIS accelerated spatial index search
                cur.execute("""
                    SELECT *,
                           ROUND((ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) / 1000.0)::numeric, 2) AS distance_km
                    FROM companies
                    WHERE geom IS NOT NULL
                      AND ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s * 1000.0)
                    ORDER BY distance_km ASC
                    LIMIT %s
                """, (lon, lat, lon, lat, rad, lim))
                return [dict(r) for r in cur.fetchall()]
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                # 2. Haversine spherical distance fallback
                cur.execute("""
                    SELECT * FROM (
                        SELECT *,
                               ROUND((6371.0 * acos(
                                   LEAST(1.0, GREATEST(-1.0,
                                       cos(radians(%s)) * cos(radians(latitude)) *
                                       cos(radians(longitude) - radians(%s)) +
                                       sin(radians(%s)) * sin(radians(latitude))
                                   ))
                               ))::numeric, 2) AS distance_km
                        FROM companies
                        WHERE latitude IS NOT NULL AND longitude IS NOT NULL
                    ) sub
                    WHERE distance_km <= %s
                    ORDER BY distance_km ASC
                    LIMIT %s
                """, (lat, lon, lat, rad, lim))
                return [dict(r) for r in cur.fetchall()]
        return []
    except Exception as e:
        logger.debug("find_nearby_companies query fallback: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return []
    finally:
        cur.close()


def log_data_source(conn, run_id: str, source_name: str, source_type: str,
                    fetched: int = 0, merged: int = 0, skipped: int = 0,
                    status: str = "DONE", notes: str = None) -> None:
    """Records a completed ingestion run in the data_sources table."""
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO data_sources
                (run_id, source_name, source_type, records_fetched,
                 records_merged, records_skipped, status, completed_at, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), %s)
            ON CONFLICT (run_id) DO UPDATE SET
                records_fetched  = EXCLUDED.records_fetched,
                records_merged   = EXCLUDED.records_merged,
                records_skipped  = EXCLUDED.records_skipped,
                status           = EXCLUDED.status,
                completed_at     = NOW(),
                notes            = EXCLUDED.notes
        """, (run_id, source_name, source_type, fetched, merged, skipped, status, notes))
    finally:
        cur.close()



if __name__ == "__main__":
    print(f"[TEST] Testing database connection -> {db_info()}")
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT COUNT(1) FROM companies")
            c_cnt = cur.fetchone()[0]
            cur.execute("SELECT COUNT(1) FROM people")
            p_cnt = cur.fetchone()[0]
            print(f"[SUCCESS] Connected! Companies: {c_cnt:,} | People: {p_cnt:,}")
    except Exception as e:
        print(f"[ERROR] Connection test failed: {e}")
