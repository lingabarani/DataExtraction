"""
DataExtraction — Buying Committee & Org Chart Hierarchy Engine
=============================================================
Provides NLP-based role classification and hierarchy reconstruction:
  1. Buying Committee Classification:
     - ECONOMIC_BUYER: Budget release authority (CFO, CEO, Finance VP).
     - TECHNICAL_EVALUATOR: Architecture & feasibility reviewers (CTO, VP Eng, IT Director).
     - CHAMPION: Problem owners and internal drivers (Staff/Principal Eng, Product Leads).
     - DECISION_MAKER: Executive sign-off stakeholders.
     - BLOCKER: Compliance, Procurement, and Legal gatekeepers.
     - INFLUENCER: Domain practitioners and individual contributors.
  2. Management Level Hierarchy:
     - C_SUITE -> VP -> DIRECTOR -> MANAGER -> INDIVIDUAL_CONTRIBUTOR.
  3. Org Chart Tree Reconstruction:
     - Self-referential tree resolution (reports_to_person_id) based on department & seniority.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("dataextraction.domain.buying_committee")

# Title Regex Patterns for Buying Roles
ROLE_PATTERNS: List[Tuple[str, re.Pattern]] = [
    (
        "ECONOMIC_BUYER",
        re.compile(
            r"\b(chief financial officer|cfo|chief executive officer|ceo|president|vp (?:of )?finance|vice president (?:of )?finance|director (?:of )?finance|head of finance|treasurer)\b",
            re.I,
        ),
    ),
    (
        "TECHNICAL_EVALUATOR",
        re.compile(
            r"\b(chief technology officer|cto|chief information officer|cio|chief security officer|ciso|vp (?:of )?engineering|vice president (?:of )?engineering|director (?:of )?engineering|engineering director|head of engineering|head of infrastructure|chief architect|principal architect|vp (?:of )?it|director (?:of )?it|head of it)\b",
            re.I,
        ),
    ),
    (
        "BLOCKER",
        re.compile(
            r"\b(procurement|general counsel|chief legal officer|compliance officer|risk management|purchasing manager|vendor management|director (?:of )?procurement|head of procurement)\b",
            re.I,
        ),
    ),
    (
        "DECISION_MAKER",
        re.compile(
            r"\b(chief operating officer|coo|managing director|executive director|general manager|partner|founder|co-founder)\b",
            re.I,
        ),
    ),
    (
        "CHAMPION",
        re.compile(
            r"\b(principal|staff|lead engineer|tech lead|senior engineering manager|group product manager|head of product|director (?:of )?product)\b",
            re.I,
        ),
    ),
]

LEVEL_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("C_SUITE", re.compile(r"\b(chief|c-level|ceo|cfo|cto|coo|cio|ciso|cro|cmo|founder|president)\b", re.I)),
    ("VP", re.compile(r"\b(vp|vice president|svp|evp)\b", re.I)),
    ("DIRECTOR", re.compile(r"\b(director|head of)\b", re.I)),
    ("MANAGER", re.compile(r"\b(manager|lead|supervisor)\b", re.I)),
]


class BuyingCommitteeClassifier:
    """
    Classifies executive titles and infers organizational reporting hierarchies.
    """

    @classmethod
    def classify_title(cls, title: Optional[str]) -> Tuple[str, str]:
        """
        Classifies an executive title into (buying_role, management_level).
        Returns defaults ("INFLUENCER", "INDIVIDUAL_CONTRIBUTOR") if no pattern matches.
        """
        if not title or not str(title).strip():
            return "INFLUENCER", "INDIVIDUAL_CONTRIBUTOR"

        cleaned_title = str(title).strip()

        # 1. Determine Buying Role
        buying_role = "INFLUENCER"
        for role, pattern in ROLE_PATTERNS:
            if pattern.search(cleaned_title):
                buying_role = role
                break

        # 2. Determine Management Level
        mgt_level = "INDIVIDUAL_CONTRIBUTOR"
        for level, pattern in LEVEL_PATTERNS:
            if pattern.search(cleaned_title):
                mgt_level = level
                break

        return buying_role, mgt_level

    @classmethod
    def reconstruct_org_chart(
        cls,
        employees: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Infers hierarchical reporting lines within an organization's roster.
        Sorts employees by management level (C-Suite -> VP -> Director -> Manager -> IC)
        and assigns `reports_to_person_id` within matching functional departments.

        Returns list of enriched employee dicts with reports_to_person_id and org_chart_depth.
        """
        if not employees:
            return []

        # Level hierarchy rank (higher number = higher authority)
        rank_map = {
            "C_SUITE": 5,
            "VP": 4,
            "DIRECTOR": 3,
            "MANAGER": 2,
            "INDIVIDUAL_CONTRIBUTOR": 1,
        }

        # Normalize and rank employees
        ranked_emps: List[Dict[str, Any]] = []
        for emp in employees:
            e = dict(emp)
            title = e.get("title") or e.get("current_primary_title") or ""
            role, level = cls.classify_title(title)
            e["buying_role"] = e.get("buying_role") or role
            e["management_level"] = level
            e["_rank"] = rank_map.get(level, 1)
            e["_dept"] = str(e.get("department") or "GENERAL").strip().upper()
            ranked_emps.append(e)

        # Sort descending by seniority rank
        ranked_emps.sort(key=lambda x: x["_rank"], reverse=True)

        # Find CEO / highest C-Suite executive
        c_suite_leaders = [e for e in ranked_emps if e["_rank"] == 5]
        top_leader_id = c_suite_leaders[0].get("id") or c_suite_leaders[0].get("person_id") if c_suite_leaders else None

        # Build department manager lookup
        # dept -> list of leaders sorted by rank descending
        dept_leaders: Dict[str, List[Dict[str, Any]]] = {}
        for e in ranked_emps:
            d = e["_dept"]
            dept_leaders.setdefault(d, []).append(e)

        # Assign reports_to and depth
        for e in ranked_emps:
            emp_id = e.get("id") or e.get("person_id")
            rank = e["_rank"]
            dept = e["_dept"]

            # C-Suite either reports to no one (CEO) or reports to CEO
            if rank == 5:
                if emp_id != top_leader_id and top_leader_id:
                    e["reports_to_person_id"] = str(top_leader_id)
                    e["org_chart_depth"] = 2
                else:
                    e["reports_to_person_id"] = None
                    e["org_chart_depth"] = 1
                continue

            # Find direct superior in the same department with higher rank
            superiors = [s for s in dept_leaders.get(dept, []) if s["_rank"] > rank and (s.get("id") or s.get("person_id")) != emp_id]
            if superiors:
                direct_manager = superiors[-1]  # Closest higher rank
                mgr_id = direct_manager.get("id") or direct_manager.get("person_id")
                e["reports_to_person_id"] = str(mgr_id) if mgr_id else None
                e["org_chart_depth"] = direct_manager.get("org_chart_depth", 2) + 1
            elif top_leader_id and emp_id != top_leader_id:
                # Fallback report to C-Suite top leader
                e["reports_to_person_id"] = str(top_leader_id)
                e["org_chart_depth"] = 2
            else:
                e["reports_to_person_id"] = None
                e["org_chart_depth"] = 1

        # Clean temporary keys after all assignments
        for e in ranked_emps:
            e.pop("_rank", None)
            e.pop("_dept", None)

        return ranked_emps


buying_committee_classifier = BuyingCommitteeClassifier()
