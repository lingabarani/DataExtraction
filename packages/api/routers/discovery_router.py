"""
Discovery Engine API.

POST /api/v1/discovery/search                 start a search (returns id + stream url)
GET  /api/v1/discovery/search/{id}/stream     Server-Sent Events: plan, source_started, result, snapshot (merged
                                              cards so far), source_done, entities_resolved, answer, done
                                              (replayed from the database when finished)
Filters: max_results (1-1000), sources ("all" | "internet": skip the saved database), crawl_websites (bool,
default true: read organization websites for emails and staff), include_unverified (bool).
GET  /api/v1/discovery/search/{id}            final answer (runs the search synchronously if it has not started)
GET  /api/v1/discovery/searches               history
GET  /api/v1/discovery/organizations/{id}     stored organization with every fact and its source
GET  /api/v1/discovery/people/{id}            stored person with provenance (suppressed people are never returned)
POST /api/v1/discovery/search/{id}/export     CSV or JSONL
GET  /api/v1/discovery/sources/status         source health (admin)
All routes require authentication like the rest of the API.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import uuid
from collections import OrderedDict
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from packages.api.dependencies import UserPrincipal, get_current_user, require_admin
from packages.discovery.orchestrator import MAX_RESULTS_LIMIT, DiscoveryOrchestrator
from packages.discovery.persistence import get_search_run
from packages.infrastructure.db_connector import get_connection, release_connection

logger = logging.getLogger("api.discovery")

router = APIRouter(prefix="/api/v1/discovery", tags=["Discovery Engine"])

MAX_LIVE_SESSIONS = 200
_active_searches: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_orchestrator = DiscoveryOrchestrator()
_ALLOWED_FILTERS = {"include_unverified", "max_results", "sources", "crawl_websites"}
_SOURCE_MODES = {"all", "internet"}  # internet = live web sources only, skip the saved database


class DiscoverySearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=300)
    filters: Dict[str, Any] = Field(default_factory=dict)
    budget_seconds: float = Field(45.0, ge=5.0, le=120.0)

    @field_validator("filters")
    @classmethod
    def _whitelist_filters(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        unknown = set(v) - _ALLOWED_FILTERS
        if unknown:
            raise ValueError(f"unsupported filters: {sorted(unknown)}")
        if "max_results" in v:
            try:
                n = int(v["max_results"])
            except (TypeError, ValueError):
                raise ValueError("max_results must be a whole number")
            if not 1 <= n <= MAX_RESULTS_LIMIT:
                raise ValueError(f"max_results must be between 1 and {MAX_RESULTS_LIMIT}")
            v["max_results"] = n
        if "sources" in v and v["sources"] not in _SOURCE_MODES:
            raise ValueError(f"sources must be one of {sorted(_SOURCE_MODES)}")
        for flag in ("include_unverified", "crawl_websites"):
            if flag in v and not isinstance(v[flag], bool):
                raise ValueError(f"{flag} must be true or false")
        return v


class DiscoverySearchInitResponse(BaseModel):
    search_id: str
    query: str
    stream_url: str


def _remember(search_id: str, session: Dict[str, Any]) -> None:
    _active_searches[search_id] = session
    while len(_active_searches) > MAX_LIVE_SESSIONS:
        _active_searches.popitem(last=False)


def _valid_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")


@router.post("/search", response_model=DiscoverySearchInitResponse, status_code=status.HTTP_202_ACCEPTED,
             summary="Start a multi-source discovery search")
async def init_search(req: DiscoverySearchRequest,
                      current_user: UserPrincipal = Depends(get_current_user)) -> DiscoverySearchInitResponse:
    query = req.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query string cannot be empty")
    search_id = str(uuid4())
    _remember(search_id, {"search_id": search_id, "query": query, "filters": req.filters,
                          "budget_seconds": req.budget_seconds, "status": "pending", "answer": None,
                          "user": current_user.email})
    return DiscoverySearchInitResponse(search_id=search_id, query=query,
                                       stream_url=f"/api/v1/discovery/search/{search_id}/stream")


@router.get("/search/{search_id}/stream", summary="Stream discovery events (SSE)")
async def stream_search(search_id: str, current_user: UserPrincipal = Depends(get_current_user)) -> StreamingResponse:
    search_id = _valid_uuid(search_id)
    session = _active_searches.get(search_id)

    if session is None or session["status"] in ("completed", "error"):
        stored = (session or {}).get("answer") or await asyncio.to_thread(get_search_run, search_id)
        if not stored:
            raise HTTPException(status_code=404, detail="Search session not found")

        async def replay() -> AsyncIterator[str]:
            yield f"event: answer\ndata: {json.dumps(stored, default=str)}\n\n"
            yield f"event: done\ndata: {json.dumps({'search_id': search_id, 'status': 'completed', 'replayed': True})}\n\n"

        return StreamingResponse(replay(), media_type="text/event-stream")

    if session["status"] == "running":
        raise HTTPException(status_code=409, detail="This search is already streaming")

    async def sse() -> AsyncIterator[str]:
        session["status"] = "running"
        try:
            async for msg in _orchestrator.search_stream(
                query=session["query"], filters=session["filters"], budget_seconds=session["budget_seconds"],
                search_id=search_id, requested_by=session.get("user"),
            ):
                name = msg.get("event", "message")
                if name == "answer":
                    session["answer"] = msg.get("data")
                yield f"event: {name}\ndata: {json.dumps(msg.get('data', {}), default=str)}\n\n"
            session["status"] = "completed"
        except asyncio.CancelledError:
            session["status"] = "pending"  # client went away before the answer: allow a retry
            raise
        except Exception as exc:
            logger.error("SSE stream error for search %s: %s", search_id, exc, exc_info=True)
            session["status"] = "error"
            yield f"event: error\ndata: {json.dumps({'error': type(exc).__name__})}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@router.get("/search/{search_id}", summary="Final answer of a search")
async def get_search_result(search_id: str, current_user: UserPrincipal = Depends(get_current_user)) -> Dict[str, Any]:
    search_id = _valid_uuid(search_id)
    session = _active_searches.get(search_id)
    if session and session.get("answer"):
        return {"search_id": search_id, "status": "completed", "query": session["query"], "answer": session["answer"]}

    stored = await asyncio.to_thread(get_search_run, search_id)
    if stored and (stored.get("cards") or stored.get("summary_markdown")):
        return {"search_id": search_id, "status": "completed", "query": stored.get("query"), "answer": stored}

    if session and session["status"] == "pending":
        session["status"] = "running"
        try:
            answer = await _orchestrator.search(query=session["query"], filters=session["filters"],
                                                budget_seconds=session["budget_seconds"], search_id=search_id)
        except Exception:
            session["status"] = "error"
            raise HTTPException(status_code=500, detail="Search failed")
        session["answer"] = answer.model_dump()
        session["status"] = "completed"
        return {"search_id": search_id, "status": "completed", "query": session["query"], "answer": session["answer"]}
    if session:
        return {"search_id": search_id, "status": session["status"], "query": session["query"], "answer": None}
    raise HTTPException(status_code=404, detail="Search run not found")


@router.get("/searches", summary="Recent search history")
async def list_search_history(limit: int = Query(20, ge=1, le=100),
                              current_user: UserPrincipal = Depends(get_current_user)) -> List[Dict[str, Any]]:
    def _query() -> List[Dict[str, Any]]:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id::text, query, status, timings, started_at, finished_at "
                            "FROM discovery_dataextraction.search_runs ORDER BY started_at DESC LIMIT %s", (limit,))
                return [{"id": r[0], "query": r[1], "status": r[2],
                         "timings": r[3] if isinstance(r[3], dict) else json.loads(r[3] or "{}"),
                         "started_at": r[4].isoformat() if r[4] else None,
                         "finished_at": r[5].isoformat() if r[5] else None} for r in cur.fetchall()]
        finally:
            release_connection(conn)

    try:
        return await asyncio.to_thread(_query)
    except Exception as exc:
        logger.warning("History unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Search history unavailable")


def _json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def _facts(cur: Any, entity_type: str, entity_id: str) -> List[Dict[str, Any]]:
    cur.execute("SELECT field, value, source, source_url, confidence, retrieved_at "
                "FROM discovery_dataextraction.facts WHERE entity_type = %s AND entity_id = %s::uuid "
                "ORDER BY field, retrieved_at DESC", (entity_type, entity_id))
    return [{"field": f[0], "value": _json(f[1], {}), "source": f[2], "source_url": f[3], "confidence": f[4],
             "retrieved_at": f[5].isoformat() if f[5] else None} for f in cur.fetchall()]


@router.get("/organizations/{org_id}", summary="Organization with facts and provenance")
async def get_organization(org_id: str, current_user: UserPrincipal = Depends(get_current_user)) -> Dict[str, Any]:
    org_id = _valid_uuid(org_id)

    def _query() -> Optional[Dict[str, Any]]:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id::text, canonical_name, category, subcategories, address_street, address_city, address_state, "
                    "address_postal_code, latitude, longitude, phones, emails, website, domain, hours, rating, review_count, "
                    "services, regulatory, social, quality_score, first_seen, last_seen "
                    "FROM discovery_dataextraction.organizations WHERE id = %s::uuid", (org_id,))
                row = cur.fetchone()
                if not row:
                    return None
                cur.execute("SELECT id::text, full_name, title, role_type, emails, phones, profile_urls, verified, provenance "
                            "FROM discovery_dataextraction.people WHERE org_id = %s::uuid AND NOT suppressed "
                            "ORDER BY full_name", (org_id,))
                people = [{"id": p[0], "name": p[1], "title": p[2], "role_type": p[3], "emails": _json(p[4], []),
                           "phones": _json(p[5], []), "profile_urls": _json(p[6], []), "verified": p[7],
                           "provenance": p[8]} for p in cur.fetchall()]
                return {
                    "id": row[0], "name": row[1], "category": row[2], "subcategories": _json(row[3], []),
                    "address": {"street": row[4], "city": row[5], "state": row[6], "postal_code": row[7]},
                    "coordinates": {"lat": row[8], "lng": row[9]}, "phones": _json(row[10], []),
                    "emails": _json(row[11], []), "website": row[12], "domain": row[13], "hours": _json(row[14], []),
                    "rating": float(row[15]) if row[15] is not None else None, "review_count": row[16],
                    "services": _json(row[17], []), "regulatory": _json(row[18], {}), "social": _json(row[19], {}),
                    "quality_score": row[20], "first_seen": row[21].isoformat() if row[21] else None,
                    "last_seen": row[22].isoformat() if row[22] else None, "people": people,
                    "facts": _facts(cur, "organization", org_id),
                }
        finally:
            release_connection(conn)

    try:
        found = await asyncio.to_thread(_query)
    except Exception as exc:
        logger.warning("Organization lookup failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable")
    if not found:
        raise HTTPException(status_code=404, detail="Organization not found")
    return found


@router.get("/people/{person_id}", summary="Person with provenance (never returns suppressed people)")
async def get_person(person_id: str, current_user: UserPrincipal = Depends(get_current_user)) -> Dict[str, Any]:
    person_id = _valid_uuid(person_id)

    def _query() -> Optional[Dict[str, Any]]:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id::text, full_name, title, role_type, org_id::text, org_name, headline, city, region, "
                    "profile_urls, emails, phones, provenance, verified FROM discovery_dataextraction.people "
                    "WHERE id = %s::uuid AND NOT suppressed", (person_id,))
                row = cur.fetchone()
                if not row:
                    return None
                return {"id": row[0], "name": row[1], "title": row[2], "role_type": row[3], "org_id": row[4],
                        "org_name": row[5], "headline": row[6], "city": row[7], "state": row[8],
                        "profile_urls": _json(row[9], []), "emails": _json(row[10], []), "phones": _json(row[11], []),
                        "provenance": row[12], "verified": row[13], "facts": _facts(cur, "person", person_id)}
        finally:
            release_connection(conn)

    try:
        found = await asyncio.to_thread(_query)
    except Exception as exc:
        logger.warning("Person lookup failed: %s", exc)
        raise HTTPException(status_code=503, detail="Database unavailable")
    if not found:
        raise HTTPException(status_code=404, detail="Person not found")
    return found


async def _do_export_search_results(search_id: str, format: str) -> StreamingResponse:
    search_id = _valid_uuid(search_id)
    session = _active_searches.get(search_id)
    run = (session or {}).get("answer") or await asyncio.to_thread(get_search_run, search_id)
    if not run:
        raise HTTPException(status_code=404, detail="Search run not found")
    cards = run.get("cards", [])

    if format == "csv":
        def rows() -> Any:
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["org_id", "name", "category", "street", "city", "state", "postal_code", "phones", "website",
                             "emails", "google_rating", "review_count", "cms_star_rating", "nc_license", "sources"])
            yield buf.getvalue()
            for c in cards:
                buf.seek(0)
                buf.truncate(0)
                a = c.get("address") or {}
                writer.writerow([
                    c.get("org_id"), c.get("name"), c.get("category"), a.get("street"), a.get("city"), a.get("state"),
                    a.get("postal_code"), "; ".join(c.get("phones") or ([c["phone"]] if c.get("phone") else [])),
                    c.get("website"), "; ".join(f"{e.get('value')} ({e.get('label')})" for e in c.get("emails", [])),
                    c.get("rating"), c.get("review_count"), c.get("cms_star_rating"), c.get("nc_license_number"),
                    "; ".join(c.get("sources", [])),
                ])
                yield buf.getvalue()

        return StreamingResponse(rows(), media_type="text/csv",
                                 headers={"Content-Disposition": f"attachment; filename=discovery_{search_id[:8]}.csv"})

    def lines() -> Any:
        for c in cards:
            yield json.dumps(c, default=str) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Content-Disposition": f"attachment; filename=discovery_{search_id[:8]}.jsonl"})


@router.get("/search/{search_id}/export", summary="Export a finished search as CSV or JSONL (GET)", operation_id="export_search_results_get")
async def export_search_results_get(search_id: str, format: str = Query("jsonl", pattern="^(csv|jsonl)$"),
                                    current_user: UserPrincipal = Depends(get_current_user)) -> StreamingResponse:
    return await _do_export_search_results(search_id, format)


@router.post("/search/{search_id}/export", summary="Export a finished search as CSV or JSONL (POST)", operation_id="export_search_results_post")
async def export_search_results_post(search_id: str, format: str = Query("jsonl", pattern="^(csv|jsonl)$"),
                                     current_user: UserPrincipal = Depends(get_current_user)) -> StreamingResponse:
    return await _do_export_search_results(search_id, format)


@router.get("/sources/status", summary="Discovery source health (admin)")
async def get_sources_status(probe: bool = Query(False, description="Run live health probes (a few network calls)"),
                             admin: UserPrincipal = Depends(require_admin)) -> List[Dict[str, Any]]:
    from packages.scrapers.linkedin.client import LinkedInHttpClient

    adapters = list(_orchestrator.stage_a_sources)
    for extra in (_orchestrator.website_crawler, _orchestrator.linkedin_source):
        if extra is not None:
            adapters.append(extra)

    async def one(src: Any) -> Dict[str, Any]:
        name = getattr(src, "name", src.__class__.__name__)
        base = {"source": name, "type": getattr(src, "source_type", "unknown"), "weight": getattr(src, "weight", 1.0)}
        if probe and hasattr(src, "healthcheck"):
            try:
                return {**base, **(await asyncio.wait_for(src.healthcheck(), timeout=8.0))}
            except Exception as exc:
                return {**base, "status": "unavailable", "error": exc.__class__.__name__}
        return {**base, "status": "configured"}

    statuses = await asyncio.gather(*[one(s) for s in adapters])
    li = next((s for s in statuses if s["source"] == "linkedin_public"), None)
    if li is not None:
        li["auth_enabled"] = LinkedInHttpClient.is_auth_enabled()
    return list(statuses)
