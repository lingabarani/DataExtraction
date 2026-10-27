"""
US B2B Output Export Manager.
Exports company and people records to JSON, CSV, and XLSX formats.
Output schema is identical to Mexico pipeline for cross-market compatibility.
"""

import csv
import json
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from ..config.settings import settings
from ..models.company import USCanonicalCompany
from ..models.person import USDecisionMaker
from ..utils.logging import logger

# ─── Header style ───────────────────────────────────────────────────────────
HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(bold=True, color="FFFFFF", name="Calibri", size=11)
ALT_ROW_FILL = PatternFill("solid", fgColor="EBF2FA")
BORDER = Border(
    left=Side(style="thin", color="B0C4DE"),
    right=Side(style="thin", color="B0C4DE"),
    top=Side(style="thin", color="B0C4DE"),
    bottom=Side(style="thin", color="B0C4DE"),
)

# ─── Industry taxonomy for report ───────────────────────────────────────────
INDUSTRY_CATEGORIES = [
    "Technology & Software",
    "Financial Services",
    "Healthcare & Pharma",
    "Manufacturing",
    "Logistics & Transport",
    "Retail & Consumer",
    "Professional Services",
    "Energy & Mining",
    "Construction & Real Estate",
    "Agriculture & Food",
    "Media & Entertainment",
    "Nonprofit & Education",
]


class USOutputManager:
    """Manages all US B2B data exports — JSON, CSV, XLSX."""

    def __init__(self):
        self.companies_dir = settings.API_COMPANIES_DIR
        self.people_dir = settings.API_PEOPLE_DIR
        self.reports_dir = settings.API_REPORTS_DIR
        for d in (self.companies_dir, self.people_dir, self.reports_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ─── JSON Exports ─────────────────────────────────────────────────────

    def write_companies_json(
        self,
        companies: List[USCanonicalCompany],
        filename: str = "us_companies.json",
    ) -> Path:
        """Export companies to JSON."""
        path = self.companies_dir / filename
        if not companies and path.exists() and path.stat().st_size > 10:
            logger.info("Preserving existing companies JSON (0 new records)", path=str(path))
            return path
        records = [c.to_dict() for c in companies]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        logger.info("Wrote US companies JSON", path=str(path), count=len(records))
        return path

    def write_people_json(
        self,
        people: List[USDecisionMaker],
        filename: str = "us_people.json",
    ) -> Path:
        """Export people to JSON."""
        path = self.people_dir / filename
        if not people and path.exists() and path.stat().st_size > 10:
            logger.info("Preserving existing people JSON (0 new records)", path=str(path))
            return path
        records = [p.to_dict() for p in people]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        logger.info("Wrote US people JSON", path=str(path), count=len(records))
        return path

    # ─── CSV Exports ──────────────────────────────────────────────────────

    def write_companies_csv(
        self,
        companies: List[USCanonicalCompany],
        filename: str = "us_companies.csv",
    ) -> Path:
        """Export companies to CSV."""
        path = self.companies_dir / filename
        if not companies:
            return path
        rows = [_flatten_company(c) for c in companies]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        logger.info("Wrote US companies CSV", path=str(path), count=len(rows))
        return path

    def write_people_csv(
        self,
        people: List[USDecisionMaker],
        filename: str = "us_people.csv",
    ) -> Path:
        """Export people to CSV."""
        path = self.people_dir / filename
        if not people:
            return path
        rows = [p.to_dict() for p in people]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        logger.info("Wrote US people CSV", path=str(path), count=len(rows))
        return path

    # ─── XLSX Exports ─────────────────────────────────────────────────────

    def write_companies_xlsx(
        self,
        companies: List[USCanonicalCompany],
        filename: str = "us_companies.xlsx",
    ) -> Path:
        """Export companies to XLSX with styled headers."""
        path = self.companies_dir / filename
        rows = [_flatten_company(c) for c in companies]
        _write_xlsx(path, "US Companies", rows)
        logger.info("Wrote US companies XLSX", path=str(path), count=len(rows))
        return path

    def write_people_xlsx(
        self,
        people: List[USDecisionMaker],
        filename: str = "us_people.xlsx",
    ) -> Path:
        """Export people to XLSX with styled headers."""
        path = self.people_dir / filename
        rows = [p.to_dict() for p in people]
        _write_xlsx(path, "US Executives", rows)
        logger.info("Wrote US people XLSX", path=str(path), count=len(rows))
        return path

    def write_industry_report(
        self,
        companies: List[USCanonicalCompany],
        people: List[USDecisionMaker],
        filename: str = "us_leads_by_industry.xlsx",
    ) -> Path:
        """
        Export multi-tab industry report.
        One tab per industry + Summary tab. Mirrors Mexico's classify_and_export format.
        """
        path = self.reports_dir / filename
        wb = openpyxl.Workbook()
        wb.remove(wb.active)

        # Build people lookup by company_id
        people_by_company: Dict[str, List[USDecisionMaker]] = {}
        for p in people:
            people_by_company.setdefault(p.company_id, []).append(p)

        industry_counts = {}
        summary_rows = []

        for industry in INDUSTRY_CATEGORIES:
            industry_companies = [
                c for c in companies
                if (c.industry or "Professional Services") == industry
            ]
            if not industry_companies:
                continue

            industry_counts[industry] = len(industry_companies)

            # Company sheet
            ws_co = wb.create_sheet(title=f"{industry[:28]}")
            _write_sheet_rows(ws_co, [_flatten_company(c) for c in industry_companies])

            # Executive sub-sheet for this industry
            industry_execs = []
            for c in industry_companies:
                for p in people_by_company.get(c.company_id, []):
                    industry_execs.append(p)

            if industry_execs:
                ws_ex = wb.create_sheet(title=f"{industry[:24]} Execs")
                _write_sheet_rows(ws_ex, [p.to_dict() for p in industry_execs])

        # Summary sheet
        ws_sum = wb.create_sheet(title="Summary", index=0)
        ws_sum.append(["Industry", "Companies", "Executives", "% of Total"])
        _style_header_row(ws_sum)
        total_co = max(len(companies), 1)
        total_ex = max(len(people), 1)
        for ind, count in sorted(industry_counts.items(), key=lambda x: -x[1]):
            ex_count = sum(
                len(people_by_company.get(c.company_id, []))
                for c in companies
                if (c.industry or "Professional Services") == ind
            )
            ws_sum.append([ind, count, ex_count, f"{count/total_co*100:.1f}%"])
        ws_sum.append(["TOTAL", len(companies), len(people), "100%"])
        _auto_width(ws_sum)

        wb.save(path)
        logger.info("Wrote US industry report XLSX", path=str(path), industries=len(industry_counts))
        return path


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _flatten_company(c: USCanonicalCompany) -> Dict[str, Any]:
    """Flatten company to a single-level dict for CSV/XLSX export."""
    addr = c.address
    phones_str = "; ".join(
        p["value"] if isinstance(p, dict) else p.value
        for p in c.phones
    ) if c.phones else ""
    emails_str = "; ".join(
        e["value"] if isinstance(e, dict) else e.value
        for e in c.emails
    ) if c.emails else ""

    return {
        "company_id": c.company_id,
        "legal_name": c.legal_name,
        "trade_name": c.trade_name,
        "normalized_name": c.normalized_name,
        "ein": c.ein,
        "entity_type": c.entity_type,
        "cik": c.cik,
        "cage_code": c.cage_code,
        "uei": c.uei,
        "state_of_incorporation": c.state_of_incorporation,
        "website": c.website,
        "domain": c.domain,
        "industry": c.industry,
        "naics_code": c.naics_code,
        "sic_code": c.sic_code,
        "employee_count_min": c.employee_count_min,
        "employee_count_max": c.employee_count_max,
        "employee_count_source": c.employee_count_source,
        "phone": c.phone,
        "all_phones": phones_str,
        "email": c.email,
        "all_emails": emails_str,
        "street": getattr(addr, "street", None),
        "city": getattr(addr, "city", None),
        "state": getattr(addr, "state", None),
        "state_code": getattr(addr, "state_code", None),
        "zip_code": getattr(addr, "zip_code", None),
        "county": getattr(addr, "county", None),
        "country": "United States",
        "latitude": c.latitude,
        "longitude": c.longitude,
        "source_count": c.source_count,
        "data_quality_score": c.data_quality_score,
        "last_verified_at": c.last_verified_at,
    }


def _write_xlsx(path: Path, sheet_title: str, rows: List[Dict[str, Any]]) -> None:
    """Write a list of dicts to an XLSX file with styled headers."""
    if not rows:
        return
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title[:31]
    _write_sheet_rows(ws, rows)
    wb.save(path)


def _write_sheet_rows(ws, rows: List[Dict[str, Any]]) -> None:
    """Write rows to a worksheet with header styling and alternating row colors."""
    if not rows:
        return
    headers = list(rows[0].keys())
    ws.append(headers)
    _style_header_row(ws)
    for i, row in enumerate(rows, 2):
        ws.append([row.get(h) for h in headers])
        if i % 2 == 0:
            for cell in ws[i]:
                cell.fill = ALT_ROW_FILL
    _auto_width(ws)


def _style_header_row(ws) -> None:
    """Apply dark blue header styling to row 1."""
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=False)
        cell.border = BORDER
    ws.row_dimensions[1].height = 20


def _auto_width(ws, max_sample: int = 100) -> None:
    """Set column widths based on sampling of content."""
    for col_idx, column in enumerate(ws.columns, 1):
        sample = [str(cell.value or "") for cell in list(column)[:max_sample]]
        max_len = max((len(v) for v in sample), default=8)
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 3, 50)


us_output_manager = USOutputManager()
