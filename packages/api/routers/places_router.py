"""DataExtraction — Deep place data router (details, services, contacts, people, reviews)."""

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from packages.api.dependencies import UserPrincipal, get_current_user, require_admin
from packages.infrastructure.db_connector import get_db_cursor
from packages.temporal.config import QUEUE_GEOSPATIAL

router = APIRouter(prefix="/api/v1/places", tags=["Places"])


class ExtractRequest(BaseModel):
    place_ids: Optional[List[str]] = Field(None, max_length=500)
    region: Optional[str] = Field(None, pattern=r"^[A-Za-z]{2}(-[A-Za-z0-9]{1,3})?$")
    category: Optional[str] = Field(None, max_length=40)
    max_places: int = Field(25, ge=1, le=500)
    batch_size: int = Field(25, ge=1, le=50)
    with_llm: bool = True
    max_reviews: Optional[int] = Field(None, ge=0, le=2000)


def _rows(cur: Any) -> List[Dict[str, Any]]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@router.get("")
def list_places(q: Optional[str] = Query(None, max_length=80), limit: int = Query(25, ge=1, le=100),
                offset: int = Query(0, ge=0), _user: UserPrincipal = Depends(get_current_user)) -> Dict[str, Any]:
    sql = ("SELECT place_id, name, city, region, rating, review_count, status, scraped_at "
           "FROM staging_dataextraction.place_details")
    params: List[Any] = []
    if q:
        sql += " WHERE name ILIKE %s"
        params.append(f"%{q}%")
    sql += " ORDER BY scraped_at DESC LIMIT %s OFFSET %s"
    params += [limit, offset]
    with get_db_cursor() as (_c, cur):
        cur.execute(sql, tuple(params))
        return {"places": _rows(cur)}


@router.get("/{place_id}")
def get_place(place_id: str, _user: UserPrincipal = Depends(get_current_user)) -> Dict[str, Any]:
    with get_db_cursor() as (_c, cur):
        cur.execute("SELECT * FROM staging_dataextraction.place_details WHERE place_id = %s", (place_id,))
        found = _rows(cur)
        if not found:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Place not found")
        details = found[0]
        cur.execute("SELECT group_name, service_name, is_enabled, display_value, origin "
                    "FROM staging_dataextraction.place_services WHERE place_id = %s "
                    "ORDER BY group_name, service_name", (place_id,))
        services = _rows(cur)
        cur.execute("SELECT contact_type, value, label, extraction_method, source_url "
                    "FROM staging_dataextraction.place_contacts WHERE place_id = %s "
                    "ORDER BY contact_type, value", (place_id,))
        contacts = _rows(cur)
        cur.execute("SELECT full_name, role_title, email, phone, extraction_method, source_url "
                    "FROM staging_dataextraction.place_people WHERE place_id = %s "
                    "ORDER BY full_name", (place_id,))
        people = _rows(cur)
        cur.execute("SELECT COUNT(*), AVG(rating) FROM staging_dataextraction.place_reviews WHERE place_id = %s",
                    (place_id,))
        n, avg = cur.fetchone()
    return {"place": details, "services": services, "contacts": contacts, "people": people,
            "reviews_summary": {"stored": int(n or 0), "average_rating": float(avg) if avg is not None else None}}


@router.get("/{place_id}/reviews")
def get_reviews(place_id: str, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                _user: UserPrincipal = Depends(get_current_user)) -> Dict[str, Any]:
    with get_db_cursor() as (_c, cur):
        cur.execute("SELECT COUNT(*) FROM staging_dataextraction.place_reviews WHERE place_id = %s", (place_id,))
        total = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT review_id, reviewer_name, LEFT(COALESCE(reviewer_name_hash, ''), 8) AS reviewer_hash_prefix,
                   rating, review_text, language, published_at, owner_response_text, sentiment, topics
            FROM staging_dataextraction.place_reviews
            WHERE place_id = %s
            ORDER BY published_at DESC NULLS LAST, id DESC
            LIMIT %s OFFSET %s
            """, (place_id, limit, offset))
        reviews = _rows(cur)
    return {"total": total, "limit": limit, "offset": offset, "reviews": reviews}


@router.post("/extract", status_code=status.HTTP_202_ACCEPTED)
async def start_extraction(body: ExtractRequest, _admin: UserPrincipal = Depends(require_admin)) -> Dict[str, Any]:
    """Start a PlaceDeepExtractionWorkflow. Needs Temporal and a geospatial worker."""
    if not body.place_ids and not body.region and not body.category:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Provide place_ids, or a region and/or category to select places")
    config = body.model_dump(exclude_none=True)
    config["max_places"] = min(body.max_places, len(body.place_ids)) if body.place_ids else body.max_places
    try:
        from packages.temporal.client import get_temporal_client
        client = await get_temporal_client()
        wf_id = f"place-deep-{uuid.uuid4().hex[:12]}"
        await client.start_workflow("PlaceDeepExtractionWorkflow", config, id=wf_id, task_queue=QUEUE_GEOSPATIAL)
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            f"Could not start workflow: {type(exc).__name__}")
    return {"workflow_id": wf_id, "task_queue": QUEUE_GEOSPATIAL, "config": config}
