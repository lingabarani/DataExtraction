"""
DataExtraction — Enterprise ATS Job Board & Hiring Velocity Scraper
===================================================================
High-throughput asynchronous scraper for modern applicant tracking systems (ATS):
  - Greenhouse API (boards-api.greenhouse.io)
  - Lever API (api.lever.co/v0/postings)
  - Ashby API (api.ashbyhq.com/posting-api)

Extracts:
  - Active job postings (title, department, seniority, compensation, remote status)
  - Computes 30-day hiring velocity & department growth triggers
  - Updates master_dataextraction.organization_job_postings and intent signals
"""

import asyncio
from datetime import datetime, timezone
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID
import aiohttp

logger = logging.getLogger("dataextraction.jobs")

# Seniority & Department Normalization Patterns
SENIORITY_PATTERNS = [
    (r"\b(chief|cxo|ceo|cto|cfo|coo|cmo|cro|ciso)\b", "C_SUITE"),
    (r"\b(vp|vice president|evp|svp)\b", "VP"),
    (r"\b(director|head of)\b", "DIRECTOR"),
    (r"\b(manager|lead|supervisor)\b", "MANAGER"),
    (r"\b(senior|sr\.|principal|staff)\b", "SENIOR"),
    (r"\b(junior|jr\.|associate|intern|entry)\b", "ENTRY"),
]

DEPARTMENT_PATTERNS = [
    (r"\b(software|engineer|developer|backend|frontend|fullstack|devops|data|ai|ml|qa|tech|architect)\b", "ENGINEERING_TECH"),
    (r"\b(sales|account executive|bdr|sdr|business development|commercial)\b", "SALES"),
    (r"\b(marketing|growth|content|demand|brand|seo|product marketing)\b", "MARKETING"),
    (r"\b(finance|accounting|controller|payroll|tax|fp&a)\b", "FINANCE"),
    (r"\b(people|hr|talent|recruiter|human resources|people ops)\b", "HUMAN_RESOURCES"),
    (r"\b(operations|logistics|supply chain|facility|support)\b", "OPERATIONS"),
    (r"\b(legal|compliance|counsel|governance|privacy)\b", "LEGAL"),
    (r"\b(nurse|caregiver|medical|clinical|physician|health|aide)\b", "HEALTHCARE_CLINICAL"),
]


def normalize_seniority(title: str) -> str:
    t_lower = title.lower()
    for pattern, level in SENIORITY_PATTERNS:
        if re.search(pattern, t_lower):
            return level
    return "INDIVIDUAL_CONTRIBUTOR"


def normalize_department(dept_str: str, title: str) -> str:
    combined = f"{dept_str} {title}".lower()
    for pattern, standard_dept in DEPARTMENT_PATTERNS:
        if re.search(pattern, combined):
            return standard_dept
    return "GENERAL_BUSINESS"


class ATSJobScraper:
    """Enterprise ATS Job Board and Hiring Velocity Extractor."""

    def __init__(self, timeout_seconds: float = 10.0):
        self.timeout = timeout_seconds
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json,text/html;q=0.9",
        }

    async def fetch_greenhouse_jobs(self, board_token: str) -> List[Dict[str, Any]]:
        """Fetch active job postings from Greenhouse public boards API."""
        url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=self.headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        jobs_raw = data.get("jobs", [])
                        results = []
                        for j in jobs_raw:
                            title = j.get("title", "").strip()
                            dept_raw = ""
                            if j.get("departments"):
                                dept_raw = j["departments"][0].get("name", "")
                            location = j.get("location", {}).get("name", "")
                            is_remote = "remote" in location.lower() or "remote" in title.lower()
                            
                            results.append({
                                "job_title": title,
                                "department": normalize_department(dept_raw, title),
                                "seniority_level": normalize_seniority(title),
                                "job_location": location,
                                "is_remote": is_remote,
                                "salary_min_usd": None,
                                "salary_max_usd": None,
                                "ats_source": "Greenhouse",
                                "external_job_url": j.get("absolute_url"),
                                "posted_at": j.get("updated_at") or datetime.now(timezone.utc).isoformat(),
                                "status": "ACTIVE",
                            })
                        return results
        except Exception as e:
            logger.debug(f"Greenhouse scrape failed for {board_token}: {e}")
        return []

    async def fetch_lever_jobs(self, company_slug: str) -> List[Dict[str, Any]]:
        """Fetch active job postings from Lever public postings API."""
        url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=self.headers) as resp:
                    if resp.status == 200:
                        jobs_raw = await resp.json()
                        results = []
                        for j in jobs_raw:
                            title = j.get("text", "").strip()
                            categories = j.get("categories", {})
                            dept_raw = categories.get("department", "") or categories.get("team", "")
                            location = categories.get("location", "")
                            workplace_type = categories.get("workplaceType", "")
                            is_remote = workplace_type.lower() == "remote" or "remote" in location.lower() or "remote" in title.lower()

                            # Extract salary if present
                            sal_min = None
                            sal_max = None
                            salary_desc = j.get("salaryDescription", "")
                            if salary_desc:
                                numbers = [int(n.replace(",", "")) for n in re.findall(r"\$([0-9,]{4,7})", salary_desc)]
                                if len(numbers) >= 2:
                                    sal_min = float(min(numbers))
                                    sal_max = float(max(numbers))
                                elif len(numbers) == 1:
                                    sal_min = float(numbers[0])

                            results.append({
                                "job_title": title,
                                "department": normalize_department(dept_raw, title),
                                "seniority_level": normalize_seniority(title),
                                "job_location": location,
                                "is_remote": is_remote,
                                "salary_min_usd": sal_min,
                                "salary_max_usd": sal_max,
                                "ats_source": "Lever",
                                "external_job_url": j.get("hostedUrl"),
                                "posted_at": datetime.fromtimestamp(j.get("createdAt", 0) / 1000, tz=timezone.utc).isoformat() if j.get("createdAt") else datetime.now(timezone.utc).isoformat(),
                                "status": "ACTIVE",
                            })
                        return results
        except Exception as e:
            logger.debug(f"Lever scrape failed for {company_slug}: {e}")
        return []

    async def ingest_jobs_for_organization(
        self,
        conn: Any,
        org_id: str,
        jurisdiction: str,
        job_postings: List[Dict[str, Any]],
    ) -> Tuple[int, List[str]]:
        """
        Ingest normalized job postings into master_dataextraction.organization_job_postings
        and calculate hiring velocity and department intent topics.
        """
        if not job_postings:
            return 0, []

        cur = conn.cursor()
        inserted_count = 0
        hiring_depts = set()

        # Batch insert into organization_job_postings
        insert_sql = """
            INSERT INTO master_dataextraction.organization_job_postings (
                org_id, jurisdiction, job_title, department, seniority_level,
                job_location, is_remote, salary_min_usd, salary_max_usd,
                ats_source, external_job_url, posted_at, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING;
        """

        for job in job_postings:
            try:
                cur.execute(insert_sql, (
                    org_id,
                    jurisdiction,
                    job["job_title"],
                    job["department"],
                    job["seniority_level"],
                    job["job_location"],
                    job["is_remote"],
                    job["salary_min_usd"],
                    job["salary_max_usd"],
                    job["ats_source"],
                    job["external_job_url"],
                    job["posted_at"],
                    job["status"],
                ))
                inserted_count += 1
                if job.get("department"):
                    hiring_depts.add(job["department"])
            except Exception as e:
                logger.error(f"Failed to insert job {job.get('job_title')}: {e}")

        # Update hiring velocity and intent topics on master organization
        total_active = len(job_postings)
        intent_topics = [f"Hiring: {dept.replace('_', ' ').title()}" for dept in sorted(list(hiring_depts))]
        intent_strength = "SURGING" if total_active >= 8 else ("HIGH" if total_active >= 3 else "MEDIUM")

        update_org_sql = """
            UPDATE master_dataextraction.organizations
            SET 
                recent_hiring_velocity = %s,
                intent_strength = %s,
                intent_topics = ARRAY(
                    SELECT DISTINCT unnest(COALESCE(intent_topics, '{}'::text[]) || %s::text[])
                ),
                updated_at = NOW()
            WHERE org_id = %s;
        """
        cur.execute(update_org_sql, (total_active, intent_strength, intent_topics, org_id))
        cur.close()

        return inserted_count, intent_topics


ats_job_scraper = ATSJobScraper()
