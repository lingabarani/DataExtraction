import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
from .db import Database

SCHEMA_COLUMNS = [
    "cid", "ftid", "place_id", "name", "address", "street_address",
    "latitude", "longitude", "website", "phone", "phone_e164",
    "category", "vertical", "vertical_raw", "country", "country_code",
    "region", "city", "postal_code", "rating", "review_count",
    "timezone", "claimed_status", "photo_thumbnail", "status",
    "attempts", "error", "created_at", "updated_at"
]

COMPACT_COLUMNS = [
    "cid", "name", "category", "rating", "review_count",
    "address", "phone", "website", "status"
]

def export_data(
    db: Database,
    export_format: str = "csv",
    output_dir: Optional[Path] = None,
    query_name: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    full: bool = False
) -> Dict[str, Any]:
    """
    Exports scraped places, reviews, hours, attributes, and photos.
    Returns generated file paths and records counts.
    """
    filters = filters or {}
    places, _ = db.query_places(
        q=filters.get("q"),
        status=filters.get("status"),
        category=filters.get("category"),
        min_rating=filters.get("min_rating"),
        min_reviews=filters.get("min_reviews"),
        has_phone=filters.get("has_phone"),
        has_website=filters.get("has_website"),
        has_photos=filters.get("has_photos"),
        claimed=filters.get("claimed"),
        vertical=filters.get("vertical"),
        country=filters.get("country"),
        city=filters.get("city"),
        has_reviews=filters.get("has_reviews"),
        has_hours=filters.get("has_hours"),
        has_attributes=filters.get("has_attributes"),
        page=1,
        page_size=1000000  # full export
    )

    if places:
        df_places = pd.DataFrame(places)
        cols_to_use = SCHEMA_COLUMNS if full else COMPACT_COLUMNS
        for col in cols_to_use:
            if col not in df_places.columns:
                df_places[col] = None
        df_places = df_places[cols_to_use]
        cids = [p["cid"] for p in places if p.get("cid")]
    else:
        cols_to_use = SCHEMA_COLUMNS if full else COMPACT_COLUMNS
        df_places = pd.DataFrame(columns=cols_to_use)
        cids = []

    with db.get_connection() as conn:
        if cids:
            placeholders = ",".join(["?"] * len(cids))
            hours_rows = conn.execute(f"SELECT * FROM hours WHERE cid IN ({placeholders})", cids).fetchall()
            attr_rows = conn.execute(f"SELECT * FROM attributes WHERE cid IN ({placeholders})", cids).fetchall()
            rev_rows = conn.execute(f"SELECT * FROM reviews WHERE cid IN ({placeholders})", cids).fetchall()
            photo_rows = conn.execute(f"SELECT * FROM photos WHERE cid IN ({placeholders})", cids).fetchall()
        else:
            hours_rows = []
            attr_rows = []
            rev_rows = []
            photo_rows = []

    df_hours = pd.DataFrame([dict(r) for r in hours_rows])
    df_attrs = pd.DataFrame([dict(r) for r in attr_rows])
    df_reviews = pd.DataFrame([dict(r) for r in rev_rows])
    df_photos = pd.DataFrame([dict(r) for r in photo_rows])

    results = {
        "places_count": len(df_places),
        "reviews_count": len(df_reviews),
        "hours_count": len(df_hours),
        "attributes_count": len(df_attrs),
        "photos_count": len(df_photos),
        "files": []
    }

    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"{query_name}_" if query_name else "gmaps_"

        dfs = {
            f"{prefix}places": df_places,
            f"{prefix}hours": df_hours,
            f"{prefix}attributes": df_attrs,
            f"{prefix}reviews": df_reviews,
            f"{prefix}photos": df_photos,
        }

        for name, df in dfs.items():
            ext = "csv" if export_format == "csv" else "jsonl" if export_format == "jsonl" else "parquet"
            filepath = output_dir / f"{name}.{ext}"
            try:
                if export_format == "csv":
                    df.to_csv(filepath, index=False, encoding="utf-8")
                elif export_format == "jsonl":
                    df.to_json(filepath, orient="records", lines=True, force_ascii=False)
                elif export_format == "parquet":
                    df.to_parquet(filepath, index=False)
            except PermissionError:
                # If file is locked by an editor or Excel on Windows, write to fallback file
                filepath = output_dir / f"{name}_latest.{ext}"
                if export_format == "csv":
                    df.to_csv(filepath, index=False, encoding="utf-8")
                elif export_format == "jsonl":
                    df.to_json(filepath, orient="records", lines=True, force_ascii=False)
                elif export_format == "parquet":
                    df.to_parquet(filepath, index=False)
            results["files"].append(str(filepath))

    return results

def export_stream_bytes(
    db: Database,
    export_format: str = "csv",
    filters: Optional[Dict[str, Any]] = None,
    full: bool = False
) -> Tuple[bytes, str]:
    """Returns places bytes and mime-type for API download."""
    filters = filters or {}
    places, _ = db.query_places(
        q=filters.get("q"),
        status=filters.get("status"),
        category=filters.get("category"),
        min_rating=filters.get("min_rating"),
        min_reviews=filters.get("min_reviews"),
        has_phone=filters.get("has_phone"),
        has_website=filters.get("has_website"),
        has_photos=filters.get("has_photos"),
        claimed=filters.get("claimed"),
        vertical=filters.get("vertical"),
        country=filters.get("country"),
        city=filters.get("city"),
        has_reviews=filters.get("has_reviews"),
        has_hours=filters.get("has_hours"),
        has_attributes=filters.get("has_attributes"),
        page=1,
        page_size=1000000
    )
    cols_to_use = SCHEMA_COLUMNS if full else COMPACT_COLUMNS
    if places:
        df = pd.DataFrame(places)
        for col in cols_to_use:
            if col not in df.columns:
                df[col] = None
        df = df[cols_to_use]
    else:
        df = pd.DataFrame(columns=cols_to_use)

    if export_format == "csv":
        buf = io.StringIO()
        df.to_csv(buf, index=False, encoding="utf-8")
        return buf.getvalue().encode("utf-8"), "text/csv"
    elif export_format == "jsonl":
        buf = io.StringIO()
        df.to_json(buf, orient="records", lines=True, force_ascii=False)
        return buf.getvalue().encode("utf-8"), "application/x-ndjson"
    elif export_format == "parquet":
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        return buf.getvalue(), "application/octet-stream"
    else:
        buf = io.StringIO()
        df.to_csv(buf, index=False, encoding="utf-8")
        return buf.getvalue().encode("utf-8"), "text/csv"


# -----------------------------------------------------------------------------
# State-Wise, Date-Wise, and Category-Wise Pipeline Exports (Section 6)
# -----------------------------------------------------------------------------

import re
import unicodedata
from datetime import datetime

STATE_EXPORT_COLUMNS = [
    "name", "cid", "country", "country_code", "region", "category",
    "address", "street_address", "latitude", "longitude", "phone",
    "phone_e164", "website", "rating", "review_count", "website_status",
    "official_website_url", "enrichment_status", "first_seen_job_id",
    "tile_id", "created_at", "updated_at"
]


def format_region_folder_name(country_code: str, region_code: str, region_name: str) -> str:
    """
    Safely normalizes region name and code into standard folder name:
    e.g. 'Alaska', 'AK' -> 'Alaska_AK'
    e.g. 'Ciudad de México', 'CMX' -> 'Ciudad_de_Mexico_CMX'
    e.g. 'Estado de México', 'MEX' -> 'Estado_de_Mexico_MEX'
    """
    norm = unicodedata.normalize('NFKD', region_name).encode('ASCII', 'ignore').decode('utf-8')
    slug = re.sub(r'[^a-zA-Z0-9]+', '_', norm.strip()).strip('_')
    return f"{slug}_{region_code.strip().upper()}"


def resolve_safe_export_path(base_dir: Path, requested_rel_path: str) -> Path:
    """
    Validates that requested relative path stays strictly within base exports directory.
    Guards against path traversal (e.g. '../..').
    """
    clean_rel = Path(requested_rel_path).as_posix().lstrip("/\\")
    target_path = (base_dir / clean_rel).resolve()
    base_resolved = base_dir.resolve()
    try:
        target_path.relative_to(base_resolved)
    except ValueError:
        raise PermissionError(f"Access denied: Path '{requested_rel_path}' is outside exports directory.")
    return target_path


def export_state_category_data(
    db: Database,
    base_exports_dir: Path,
    run_id: str,
    run_date: str,
    country_code: str,
    region_code: str,
    region_name: str,
    category: str,
    export_format: str = "csv"
) -> Dict[str, Any]:
    """
    Exports a single category's collected businesses for a state into its organized folder:
    data/exports/YYYY-MM-DD/COUNTRY/REGION_NAME_REGION_CODE/<category_slug>.csv
    """
    cc = country_code.strip().upper()
    rc = region_code.strip().upper()
    folder_name = format_region_folder_name(cc, rc, region_name)
    export_dir = base_exports_dir / run_date / cc / folder_name
    export_dir.mkdir(parents=True, exist_ok=True)

    cat_slug = re.sub(r'[^a-zA-Z0-9]+', '_', category.strip().lower()).strip('_') or "all"

    # Query businesses matching country, region, category/vertical
    with db.get_connection() as conn:
        if cat_slug in ("all", "all_businesses"):
            rows = conn.execute("""
                SELECT * FROM places
                WHERE country_code = ? AND region = ?
                ORDER BY name ASC, cid ASC
            """, (cc, rc)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM places
                WHERE country_code = ? AND region = ?
                AND (lower(vertical) = lower(?) OR lower(category) = lower(?))
                ORDER BY name ASC, cid ASC
            """, (cc, rc, category, category)).fetchall()
        places = [dict(r) for r in rows]

    df = pd.DataFrame(places) if places else pd.DataFrame(columns=STATE_EXPORT_COLUMNS)
    for col in STATE_EXPORT_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[STATE_EXPORT_COLUMNS]

    # Guard and verify: exported row count must strictly match database query result
    if len(df) != len(places):
        raise ValueError(
            f"Export row count mismatch for {cc}-{rc} category '{category}': "
            f"DataFrame has {len(df)} rows, database query returned {len(places)}."
        )

    filename = f"{cat_slug}.{export_format}"
    filepath = export_dir / filename

    if export_format == "csv":
        df.to_csv(filepath, index=False, encoding="utf-8")
    elif export_format == "jsonl":
        df.to_json(filepath, orient="records", lines=True, force_ascii=False)
    else:
        df.to_csv(filepath, index=False, encoding="utf-8")

    return {
        "category": category,
        "count": len(df),
        "file": str(filepath),
        "rel_path": str(filepath.relative_to(base_exports_dir)),
    }


def export_state_complete_package(
    db: Database,
    base_exports_dir: Optional[Path] = None,
    run_id: str = "manual_export",
    run_date: Optional[str] = None,
    country_code: Optional[str] = None,
    region_code: Optional[str] = None,
    region_name: Optional[str] = None,
    categories: Optional[List[str]] = None,
    export_format: str = "csv",
    **kwargs: Any
) -> Dict[str, Any]:
    """
    Generates or refreshes the full state package after all selected tasks finish:
    - <category_slug>.csv for each category
    - all_businesses.csv
    - run_summary.json (with tile completeness metrics)
    """
    if base_exports_dir is None:
        base_exports_dir = kwargs.get("exports_base_dir")
    if base_exports_dir is None:
        raise ValueError("base_exports_dir is required")
    base_exports_dir = Path(base_exports_dir)

    cc = (country_code or kwargs.get("country", "US")).strip().upper()
    rc = (region_code or kwargs.get("region", "")).strip().upper()

    if not run_date:
        run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if not region_name:
        try:
            from .scope import get_region
            region_name = get_region(cc, rc).name
        except Exception:
            region_name = rc

    if categories is None:
        from .orchestrator import DEFAULT_CATEGORIES
        db_cats = set()
        with db.get_connection() as conn:
            c_rows = conn.execute("""
                SELECT DISTINCT category FROM places WHERE country_code = ? AND region = ? AND category IS NOT NULL
                UNION
                SELECT DISTINCT vertical FROM places WHERE country_code = ? AND region = ? AND vertical IS NOT NULL
                UNION
                SELECT DISTINCT category FROM geographic_tiles WHERE country_code = ? AND region_code = ? AND category IS NOT NULL
            """, (cc, rc, cc, rc, cc, rc)).fetchall()
            for r in c_rows:
                if r[0] and str(r[0]).strip():
                    db_cats.add(str(r[0]).strip())

        seen = set()
        categories = []
        for c in list(DEFAULT_CATEGORIES) + sorted(db_cats):
            if c not in seen:
                seen.add(c)
                categories.append(c)

    folder_name = format_region_folder_name(cc, rc, region_name)
    export_dir = base_exports_dir / run_date / cc / folder_name
    export_dir.mkdir(parents=True, exist_ok=True)

    category_files: List[Dict[str, Any]] = []
    category_counts: Dict[str, int] = {}

    for cat in categories:
        res = export_state_category_data(
            db=db,
            base_exports_dir=base_exports_dir,
            run_id=run_id,
            run_date=run_date,
            country_code=cc,
            region_code=rc,
            region_name=region_name,
            category=cat,
            export_format=export_format
        )
        category_files.append(res)
        category_counts[cat] = res["count"]

    # Generate all_businesses.csv
    with db.get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM places
            WHERE country_code = ? AND region = ?
            ORDER BY name ASC, cid ASC
        """, (cc, rc)).fetchall()
        all_places = [dict(r) for r in rows]

    df_all = pd.DataFrame(all_places) if all_places else pd.DataFrame(columns=STATE_EXPORT_COLUMNS)
    for col in STATE_EXPORT_COLUMNS:
        if col not in df_all.columns:
            df_all[col] = None
    df_all = df_all[STATE_EXPORT_COLUMNS]

    all_file = export_dir / f"all_businesses.{export_format}"
    if export_format == "csv":
        df_all.to_csv(all_file, index=False, encoding="utf-8")
    elif export_format == "jsonl":
        df_all.to_json(all_file, orient="records", lines=True, force_ascii=False)
    else:
        df_all.to_csv(all_file, index=False, encoding="utf-8")

    # Fetch geographic tile metrics for this region
    tile_counts = db.get_pipeline_tile_counts(country_code=cc, region_code=rc)
    has_incomplete = (
        tile_counts.get("pending", 0) > 0 or
        tile_counts.get("running", 0) > 0 or
        tile_counts.get("retry_pending", 0) > 0 or
        tile_counts.get("failed", 0) > 0
    )

    if tile_counts.get("total", 0) == 0:
        completeness = "pending"
    elif has_incomplete:
        completeness = "partially_completed"
    else:
        completeness = "fully_completed"

    # Count websites verified & enriched in this state
    with db.get_connection() as conn:
        row_disc = conn.execute("""
            SELECT count(*) as cnt FROM places
            WHERE country_code = ? AND region = ? AND website_status = 'verified'
        """, (cc, rc)).fetchone()
        websites_verified = row_disc["cnt"] if row_disc else 0

        row_enr = conn.execute("""
            SELECT count(*) as cnt FROM places
            WHERE country_code = ? AND region = ? AND enrichment_status = 'completed'
        """, (cc, rc)).fetchone()
        companies_enriched = row_enr["cnt"] if row_enr else 0

        # Collection errors for tasks in this region
        err_rows = conn.execute("""
            SELECT task_id, category, last_error FROM collection_tasks
            WHERE country_code = ? AND region_code = ? AND last_error IS NOT NULL
        """, (cc, rc)).fetchall()
        task_errors = [dict(e) for e in err_rows]

    summary_data = {
        "run_id": run_id,
        "run_date": run_date,
        "export_timestamp": datetime.now().isoformat(),
        "country_code": cc,
        "region_code": rc,
        "region_name": region_name,
        "folder_name": folder_name,
        "relative_folder": f"{run_date}/{cc}/{folder_name}",
        "categories_processed": categories,
        "total_businesses_in_region": len(df_all),
        "category_counts": category_counts,
        "tile_metrics": tile_counts,
        "completeness_status": completeness,
        "has_incomplete_tiles": has_incomplete,
        "websites_verified": websites_verified,
        "companies_enriched": companies_enriched,
        "errors": task_errors,
    }

    summary_file = export_dir / "run_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2, ensure_ascii=False)

    return {
        "country": cc,
        "region_code": rc,
        "region_name": region_name,
        "export_folder": str(export_dir),
        "export_dir": str(export_dir),
        "relative_dir": f"{run_date}/{cc}/{folder_name}",
        "total_businesses": len(df_all),
        "all_businesses_count": len(df_all),
        "categories": categories,
        "completeness_status": completeness,
        "summary": summary_data,
        "files": [str(all_file), str(summary_file)] + [cf["file"] for cf in category_files]
    }


def list_all_state_exports(base_exports_dir: Path) -> List[Dict[str, Any]]:
    """
    Discovers all generated state export packages and parses run_summary.json.
    Returns structured list sorted newest date first.
    """
    if not base_exports_dir.exists():
        return []

    results: List[Dict[str, Any]] = []
    # Match data/exports/YYYY-MM-DD/COUNTRY/REGION_NAME_REGION_CODE/run_summary.json
    for summary_path in base_exports_dir.glob("*/*/*/run_summary.json"):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            folder = summary_path.parent
            files = [p.name for p in folder.glob("*") if p.is_file()]
            data["files"] = files
            data["full_path"] = str(folder)
            data["total_businesses"] = data.get("total_businesses_in_region", 0)
            data["country"] = data.get("country_code")
            data["categories"] = data.get("categories_processed", [])
            data["all_businesses_csv"] = str(folder / "all_businesses.csv")
            data["run_summary_json"] = str(summary_path)
            results.append(data)
        except Exception:
            continue

    # Sort by run_date descending, then country, then region
    results.sort(key=lambda x: (x.get("run_date", ""), x.get("country_code", ""), x.get("region_code", "")), reverse=True)
    return results

