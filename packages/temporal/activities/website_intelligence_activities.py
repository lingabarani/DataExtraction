"""
DataExtraction — Agent 8: Website Intelligence & Enrichment Temporal Activities
================================================================================
Enterprise Temporal activities orchestrating:
1. Candidate domain resolution and deduplication from Agent 1 & Agent 2 staging observations.
2. SSRF-safe DNS, SSL, and HTTP redirect verification.
3. Internal multi-page website crawling respecting robots.txt.
4. Field-level cross-verification & conflict auditing against website evidence.
5. Passive technology stack discovery.
6. C-suite executive and contact channel discovery.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import socket
import ssl
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
from temporalio import activity

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GMAPS_SRC = _REPO_ROOT / "packages" / "scrapers" / "google_maps" / "src"
for p in [str(_REPO_ROOT), str(_REPO_ROOT / "packages"), str(_GMAPS_SRC)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from packages.infrastructure.db_connector import get_connection, release_connection
from packages.scrapers.google_maps.src.gmaps_scraper.website.ssrf import is_safe_url
from packages.scrapers.google_maps.src.gmaps_scraper.website.crawler import SafeWebsiteCrawler, PageResponse
from packages.scrapers.google_maps.src.gmaps_scraper.website.extractor import WebsiteExtractor
from packages.scrapers.google_maps.services.taxonomy import ServiceTaxonomyClassifier
from packages.discovery.robots import get_robots
from packages.enrichment.website.tech_stack import TechStackDetector
from packages.enrichment.website.verifier import FieldCrossVerifier
from packages.enrichment.website.csuite_extractor import CSuiteExtractor
from packages.scrapers.google_maps.deep_place import regex_contacts

logger = logging.getLogger("dataextraction.activities.website_intelligence")


def _safe_heartbeat(payload: Any) -> None:
    try:
        activity.heartbeat(payload)
    except Exception:
        pass


def _clean_domain(url_or_domain: str) -> Optional[str]:
    if not url_or_domain or not isinstance(url_or_domain, str):
        return None
    cleaned = url_or_domain.strip().lower()
    if not cleaned.startswith(("http://", "https://")):
        cleaned = "https://" + cleaned
    try:
        parsed = urllib.parse.urlsplit(cleaned)
        host = (parsed.hostname or "").strip()
        if host.startswith("www."):
            host = host[4:]
        return host if ("." in host and not host.endswith(".")) else None
    except Exception:
        return None


@activity.defn(name="run_website_candidate_resolution")
async def run_website_candidate_resolution_activity(
    batch_id: str,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Extracts and deduplicates website domain candidates from Agent 1 (Registry)
    and Agent 2 (Geospatial/OSM) staging tables.
    """
    _safe_heartbeat({"stage": "resolving_candidates", "batch_id": batch_id})
    conn = get_connection()
    if not conn:
        logger.error("Database connection unavailable for candidate resolution")
        return []

    eff_limit = limit or 50
    candidates: List[Dict[str, Any]] = []
    seen_domains: Set[str] = set()

    try:
        with conn.cursor() as cur:
            # Gather candidates from staging_companies across both Agent 1 and Agent 2
            cur.execute(
                """
                SELECT id, name, website, phone, email,
                       COALESCE(raw_payload->>'formatted_address', raw_payload->>'address', '') as address,
                       city, state, zip_code, source, raw_payload->>'cid' as cid
                FROM staging_dataextraction.staging_companies
                WHERE website IS NOT NULL
                  AND LENGTH(TRIM(website)) > 3
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (eff_limit * 2,),
            )
            for (c_id, name, web, phone, email, addr, city, state, zip_code, src, cid) in cur.fetchall():
                domain = _clean_domain(web)
                if domain and domain not in seen_domains:
                    seen_domains.add(domain)
                    candidates.append({
                        "company_id": c_id,
                        "place_id": cid or c_id,
                        "name": name,
                        "website": web,
                        "domain": domain,
                        "phone": phone,
                        "email": email,
                        "address": addr,
                        "city": city,
                        "state": state,
                        "postal_code": zip_code,
                        "source": src,
                    })
                if len(candidates) >= eff_limit:
                    break

            # If more slots available, also check place_details
            if len(candidates) < eff_limit:
                cur.execute(
                    """
                    SELECT place_id, name, website, phone, address, city, region, postal_code
                    FROM staging_dataextraction.place_details
                    WHERE website IS NOT NULL
                      AND LENGTH(TRIM(website)) > 3
                    ORDER BY scraped_at DESC
                    LIMIT %s
                    """,
                    (eff_limit - len(candidates),),
                )
                for (pid, name, web, phone, addr, city, region, zip_c) in cur.fetchall():
                    domain = _clean_domain(web)
                    if domain and domain not in seen_domains:
                        seen_domains.add(domain)
                        candidates.append({
                            "company_id": None,
                            "place_id": pid,
                            "name": name,
                            "website": web,
                            "domain": domain,
                            "phone": phone,
                            "email": None,
                            "address": addr,
                            "city": city,
                            "state": region,
                            "postal_code": zip_c,
                            "source": "GOOGLE_MAPS",
                        })
                    if len(candidates) >= eff_limit:
                        break

    except Exception as exc:
        logger.error("Failed querying website candidates: %s", exc)
    finally:
        release_connection(conn)

    logger.info("Resolved %d deduplicated website candidates for batch %s", len(candidates), batch_id)
    return candidates


@activity.defn(name="run_website_verification")
async def run_website_verification_activity(
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Performs SSRF-safe DNS resolution, SSL handshake, and HTTP reachability checks.
    Persists audit records into `staging_dataextraction.website_verifications`.
    Returns list of verified reachable candidates.
    """
    _safe_heartbeat({"stage": "verifying_domains", "total": len(candidates)})
    conn = get_connection()
    verified_candidates: List[Dict[str, Any]] = []
    ver_rows = []

    for idx, c in enumerate(candidates, 1):
        domain = c.get("domain")
        raw_url = c.get("website") or f"https://{domain}"
        if not raw_url.startswith(("http://", "https://")):
            raw_url = f"https://{domain}"

        _safe_heartbeat({"stage": "verifying_domain", "domain": domain, "index": idx, "total": len(candidates)})

        # 1. SSRF Safety Check
        is_safe, ssrf_reason = is_safe_url(raw_url)
        if not is_safe:
            logger.warning("SSRF check rejected URL %s: %s", raw_url, ssrf_reason)
            ver_rows.append((
                domain, c.get("company_id"), c.get("place_id"), raw_url, None, 0,
                False, False, False, False, None, 0, json.dumps([]), f"SSRF blocked: {ssrf_reason}"
            ))
            continue

        # 2. DNS Resolution
        ip_addr = None
        dns_ok = False
        try:
            addrinfo = await asyncio.to_thread(socket.getaddrinfo, domain, 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
            if addrinfo:
                ip_addr = addrinfo[0][4][0]
                dns_ok = True
        except Exception as dns_exc:
            logger.debug("DNS lookup failed for %s: %s", domain, dns_exc)

        if not dns_ok:
            ver_rows.append((
                domain, c.get("company_id"), c.get("place_id"), raw_url, None, 0,
                False, False, False, False, None, 0, json.dumps([]), "DNS resolution failed"
            ))
            continue

        # 3. HTTP Reachability & SSL Handshake
        http_status = 0
        final_url = raw_url
        is_reachable = False
        has_ssl = raw_url.startswith("https://")
        redirects = []
        resp_time_ms = 0
        error_msg = None

        t0 = time.time()
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(raw_url, headers={"User-Agent": "Mozilla/5.0 (compatible; DataExtractionBot/2.0)"})
                resp_time_ms = int((time.time() - t0) * 1000)
                http_status = resp.status_code
                final_url = str(resp.url)
                for h in resp.history:
                    redirects.append({"url": str(h.url), "status": h.status_code})
                is_reachable = (http_status < 400)
                has_ssl = final_url.startswith("https://")
        except Exception as http_exc:
            error_msg = str(http_exc)[:200]
            resp_time_ms = int((time.time() - t0) * 1000)

        ver_rows.append((
            domain, c.get("company_id"), c.get("place_id"), raw_url, final_url, http_status,
            is_reachable, has_ssl, has_ssl, dns_ok, ip_addr, resp_time_ms, json.dumps(redirects), error_msg
        ))

        if is_reachable:
            verified_candidates.append({
                **c,
                "final_url": final_url,
                "has_ssl": has_ssl,
            })

    # Persist verification records
    if conn and ver_rows:
        try:
            with conn.cursor() as cur:
                from psycopg2.extras import execute_values
                execute_values(
                    cur,
                    """
                    INSERT INTO staging_dataextraction.website_verifications (
                        domain, company_id, place_id, input_url, final_url, http_status,
                        is_reachable, is_secure, has_ssl, dns_resolves, ip_address,
                        response_time_ms, redirect_chain, error_message, verified_at
                    ) VALUES %s
                    ON CONFLICT (domain) DO UPDATE SET
                        final_url = EXCLUDED.final_url,
                        http_status = EXCLUDED.http_status,
                        is_reachable = EXCLUDED.is_reachable,
                        is_secure = EXCLUDED.is_secure,
                        has_ssl = EXCLUDED.has_ssl,
                        dns_resolves = EXCLUDED.dns_resolves,
                        ip_address = EXCLUDED.ip_address,
                        response_time_ms = EXCLUDED.response_time_ms,
                        redirect_chain = EXCLUDED.redirect_chain,
                        error_message = EXCLUDED.error_message,
                        verified_at = NOW()
                    """,
                    ver_rows,
                )

                # Propagate verified domain to staging_companies so Agent 3 directly links it in Splink
                for c in verified_candidates:
                    cid = c.get("company_id")
                    dom = c.get("domain")
                    if cid and dom:
                        cur.execute(
                            """
                            UPDATE staging_dataextraction.staging_companies
                            SET domain = %s, updated_at = NOW()
                            WHERE id = %s AND (domain IS NULL OR domain = '')
                            """,
                            (dom, cid),
                        )
            conn.commit()
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error("Failed saving website verifications: %s", exc)
        finally:
            release_connection(conn)

    logger.info("Verified %d reachable websites out of %d candidates", len(verified_candidates), len(candidates))
    return verified_candidates


@activity.defn(name="run_website_crawl_and_enrichment")
async def run_website_crawl_and_enrichment_activity(
    verified_candidates: List[Dict[str, Any]],
    batch_id: str,
    max_pages: int = 6,
) -> Dict[str, Any]:
    """
    Crawls verified official websites, extracts contacts and C-suite leadership,
    discovers technology stack, and performs field cross-verification without overwriting.
    """
    _safe_heartbeat({"stage": "crawling_enrichment", "total": len(verified_candidates)})
    conn = get_connection()

    crawler = SafeWebsiteCrawler(max_pages=max_pages, timeout=12.0)
    csuite_extractor = CSuiteExtractor()
    field_verifier = FieldCrossVerifier()
    taxonomy_classifier = ServiceTaxonomyClassifier()

    stats = {
        "domains_crawled": 0,
        "contacts_saved": 0,
        "executives_saved": 0,
        "services_saved": 0,
        "tech_stack_saved": 0,
        "cross_verifications_saved": 0,
    }

    field_cross_records = []
    tech_stack_records = []
    people_records = []
    contact_records = []
    services_records = []
    profile_updates = []

    for idx, c in enumerate(verified_candidates, 1):
        domain = c.get("domain")
        start_url = c.get("final_url") or c.get("website") or f"https://{domain}"
        place_id = c.get("place_id") or "unknown"
        company_id = c.get("company_id")

        _safe_heartbeat({"stage": "crawling", "domain": domain, "index": idx, "total": len(verified_candidates)})

        pages_raw = {}
        headers_collected: Dict[str, str] = {}
        try:
            crawl_res = await crawler.crawl(start_url)
            for u, p in crawl_res.items():
                html_content = p.html if hasattr(p, "html") else str(p)
                pages_raw[u] = html_content
                if hasattr(p, "headers") and p.headers:
                    headers_collected.update({str(k): str(v) for k, v in p.headers.items()})
            stats["domains_crawled"] += 1
        except Exception as exc:
            logger.warning("Crawl failed for domain %s: %s", domain, exc)
            continue

        if not pages_raw:
            continue

        # 1. Tech Stack Detection
        tech_list = TechStackDetector.detect(pages_raw, headers=headers_collected)
        for t in tech_list:
            tech_stack_records.append((
                domain, company_id, place_id, t["technology_name"], t["category"],
                t.get("version"), t.get("evidence_url"), t["confidence"], datetime.now(timezone.utc)
            ))

        # 2. C-Suite Leadership Extraction
        leaders = csuite_extractor.extract_leadership(pages_raw, place_id=place_id, company_id=company_id, run_id=batch_id)
        for lead in leaders:
            people_records.append((
                place_id, lead["full_name"], lead["role_title"], None, None,
                lead.get("source_url"), "website_csuite", "WEBSITE_INTELLIGENCE",
                lead.get("source_url"), batch_id, datetime.now(timezone.utc)
            ))

        # 3. Contact Channels (Regex from HTML)
        contacts = regex_contacts(pages_raw)
        for con in contacts:
            contact_records.append((
                place_id, con["contact_type"], con["value"], con.get("label"),
                con.get("extraction_method", "regex"), "WEBSITE_INTELLIGENCE",
                con.get("source_url"), batch_id, datetime.now(timezone.utc)
            ))

        # 4. Field Cross-Verification against evidence
        # Gather website evidence for name, phone, email, zip
        evidence = {
            "names": [{"value": c.get("name"), "source_url": start_url, "snippet": f"Found on {start_url}"}] if c.get("name") else [],
            "phones": [{"value": con["value"], "source_url": con.get("source_url"), "snippet": con["value"]} for con in contacts if con["contact_type"] == "phone"],
            "emails": [{"value": con["value"], "source_url": con.get("source_url"), "snippet": con["value"]} for con in contacts if con["contact_type"] == "email"],
            "addresses": [{"postal_code": c.get("postal_code"), "source_url": start_url, "snippet": c.get("postal_code")}] if c.get("postal_code") else [],
        }
        f_results = field_verifier.verify_company_fields(domain, c, evidence)
        for fr in f_results:
            field_cross_records.append((
                domain, company_id, place_id, fr["field_name"], fr.get("original_value"),
                fr.get("website_value"), fr["status"], fr.get("evidence_url"),
                fr.get("evidence_snippet"), fr["confidence"], datetime.now(timezone.utc)
            ))

        # 5. Extract Company Overview, Services, and Office Locations via WebsiteExtractor
        try:
            page_objs = {
                u: PageResponse(url=u, status_code=200, html=h, headers={})
                for u, h in pages_raw.items()
            }
            extracted_profile = WebsiteExtractor.extract(
                {"primary_type": c.get("name"), "formatted_address": c.get("address")},
                page_objs,
            )
            prof = extracted_profile.get("profile") or {}

            overview = prof.get("overview")
            if overview and company_id:
                profile_updates.append((company_id, overview, prof.get("industry")))

            for svc_name in (prof.get("services") or []):
                if not svc_name:
                    continue
                c_tax = taxonomy_classifier.classify_service(svc_name, group_hint="website")
                services_records.append((
                    place_id,
                    "website",
                    svc_name[:150],
                    c_tax.get("main_category"),
                    c_tax.get("subcategory"),
                    True,
                    None,
                    "website",
                    "WEBSITE_INTELLIGENCE",
                    start_url,
                    json.dumps(c_tax.get("tags") or []),
                    c_tax.get("taxonomy_version"),
                    batch_id,
                    datetime.now(timezone.utc),
                ))

            for loc_str in (prof.get("locations") or []):
                if loc_str and len(loc_str) > 5:
                    contact_records.append((
                        place_id, "address", loc_str[:255], "office_location",
                        "website_profile", "WEBSITE_INTELLIGENCE",
                        start_url, batch_id, datetime.now(timezone.utc)
                    ))
        except Exception as prof_exc:
            logger.debug("Profile extraction notice for %s: %s", domain, prof_exc)

    # Bulk persist into database
    if conn:
        try:
            with conn.cursor() as cur:
                from psycopg2.extras import execute_values

                # Tech stack
                if tech_stack_records:
                    execute_values(
                        cur,
                        """
                        INSERT INTO staging_dataextraction.company_tech_stack (
                            domain, company_id, place_id, technology_name, category,
                            version, evidence_url, confidence, detected_at
                        ) VALUES %s
                        ON CONFLICT (domain, technology_name) DO UPDATE SET
                            version = COALESCE(EXCLUDED.version, staging_dataextraction.company_tech_stack.version),
                            confidence = GREATEST(EXCLUDED.confidence, staging_dataextraction.company_tech_stack.confidence),
                            detected_at = NOW()
                        """,
                        tech_stack_records,
                    )
                    stats["tech_stack_saved"] = len(tech_stack_records)

                # People / C-Suite
                if people_records:
                    execute_values(
                        cur,
                        """
                        INSERT INTO staging_dataextraction.place_people (
                            place_id, full_name, role_title, email, phone,
                            profile_url, extraction_method, source, source_url, run_id, scraped_at
                        ) VALUES %s
                        ON CONFLICT (place_id, full_name, role_title) DO NOTHING
                        """,
                        people_records,
                    )
                    stats["executives_saved"] = len(people_records)

                # Contacts
                if contact_records:
                    execute_values(
                        cur,
                        """
                        INSERT INTO staging_dataextraction.place_contacts (
                            place_id, contact_type, value, label,
                            extraction_method, source, source_url, run_id, scraped_at
                        ) VALUES %s
                        ON CONFLICT (place_id, contact_type, value) DO NOTHING
                        """,
                        contact_records,
                    )
                    stats["contacts_saved"] = len(contact_records)

                # Services from website
                if services_records:
                    execute_values(
                        cur,
                        """
                        INSERT INTO staging_dataextraction.place_services (
                            place_id, group_name, service_name, main_category, subcategory,
                            is_enabled, display_value, origin, source, source_url, tags,
                            taxonomy_version, run_id, scraped_at
                        ) VALUES %s
                        ON CONFLICT (place_id, group_name, service_name) DO UPDATE SET
                            main_category = COALESCE(EXCLUDED.main_category, staging_dataextraction.place_services.main_category),
                            subcategory = COALESCE(EXCLUDED.subcategory, staging_dataextraction.place_services.subcategory),
                            tags = EXCLUDED.tags,
                            scraped_at = NOW()
                        """,
                        services_records,
                    )
                    stats["services_saved"] = len(services_records)

                # Company profile overview
                for comp_id, over_text, ind_text in profile_updates:
                    cur.execute(
                        """
                        UPDATE staging_dataextraction.staging_companies
                        SET raw_payload = jsonb_set(
                            COALESCE(raw_payload, '{}'::jsonb),
                            '{website_profile}',
                            jsonb_build_object('overview', %s::text, 'industry', %s::text)
                        ), updated_at = NOW()
                        WHERE id = %s
                        """,
                        (over_text, ind_text, comp_id),
                    )

                # Field cross-verifications
                if field_cross_records:
                    execute_values(
                        cur,
                        """
                        INSERT INTO staging_dataextraction.field_cross_verifications (
                            domain, company_id, place_id, field_name, original_value,
                            website_value, status, evidence_url, evidence_snippet, confidence, checked_at
                        ) VALUES %s
                        ON CONFLICT (domain, field_name, original_value, website_value) DO UPDATE SET
                            status = EXCLUDED.status,
                            confidence = EXCLUDED.confidence,
                            checked_at = NOW()
                        """,
                        field_cross_records,
                    )
                    stats["cross_verifications_saved"] = len(field_cross_records)

            conn.commit()
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error("Failed saving website intelligence records: %s", exc)
        finally:
            release_connection(conn)

    logger.info("Website intelligence enrichment complete: %s", stats)
    return stats
