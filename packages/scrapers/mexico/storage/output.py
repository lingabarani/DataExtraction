"""
Output export managers for API, Public-Directory Scraping, and Combined Ingestion Channels.
Ensures complete physical and logical separation between API and Scraped datasets.
"""

import csv
import json
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from ..config.settings import settings
from ..models.company import CanonicalCompany
from ..models.person import DecisionMaker
from ..pipeline.validation import get_company_validation_flags, get_person_validation_flags
from ..utils.logging import logger


class ApiOutputManager:
    """Manages all output files, logs, and reports for API-based ingestion."""

    def __init__(self):
        self.companies_dir = settings.API_COMPANIES_DIR
        self.people_dir = settings.API_PEOPLE_DIR
        self.logs_dir = settings.API_LOGS_DIR
        self.reports_dir = settings.API_REPORTS_DIR
        for d in (self.companies_dir, self.people_dir, self.logs_dir, self.reports_dir):
            d.mkdir(parents=True, exist_ok=True)

    def write_companies(
        self,
        companies: List[CanonicalCompany],
        filename: str = "api_companies.json",
        include_personal_contacts: Optional[bool] = None,
    ) -> Path:
        """Writes API-derived company records to output/api/companies/api_companies.json."""
        target_path = self.companies_dir / filename
        include_contacts = (
            include_personal_contacts
            if include_personal_contacts is not None
            else settings.ENABLE_PERSONAL_CONTACT_FIELDS
        )

        records = []
        for idx, c in enumerate(companies, 1):
            val_flags = get_company_validation_flags(c)
            records.append(
                c.to_channel_dict(
                    ingestion_method="api",
                    record_index=idx,
                    validation_flags=val_flags,
                    include_personal_contacts=include_contacts,
                )
            )

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)

        logger.info("Generated API companies JSON", path=str(target_path), count=len(records))
        return target_path

    def write_people(
        self,
        people: List[DecisionMaker],
        filename: str = "api_people.json",
        company_rfc_map: Optional[Dict[str, str]] = None,
        include_personal_contacts: Optional[bool] = None,
    ) -> Path:
        """Writes API-derived decision-maker records to output/api/people/api_people.json."""
        target_path = self.people_dir / filename
        include_contacts = (
            include_personal_contacts
            if include_personal_contacts is not None
            else settings.ENABLE_PERSONAL_CONTACT_FIELDS
        )
        rfc_map = company_rfc_map or {}

        records = []
        for idx, p in enumerate(people, 1):
            val_flags = get_person_validation_flags(p)
            comp_rfc = rfc_map.get(p.company_id)
            records.append(
                p.to_channel_dict(
                    ingestion_method="api",
                    record_index=idx,
                    company_rfc=comp_rfc,
                    validation_flags=val_flags,
                    include_personal_contacts=include_contacts,
                )
            )

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)

        logger.info("Generated API people JSON", path=str(target_path), count=len(records))
        return target_path

    def write_summary(self, summary_data: Dict[str, Any], filename: str = "api_summary.json") -> Path:
        """Writes machine-readable API execution summary to output/api/logs/api_summary.json."""
        target_path = self.logs_dir / filename
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2, ensure_ascii=False)
        return target_path

    def write_validation_report(self, report_data: Dict[str, Any], filename: str = "api_validation_report.json") -> Path:
        """Writes API validation report to output/api/reports/api_validation_report.json."""
        target_path = self.reports_dir / filename
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)
        return target_path


class ScrapingOutputManager:
    """Manages all output files, logs, and reports for Public-Directory Scraping ingestion."""

    def __init__(self):
        self.companies_dir = settings.SCRAPING_COMPANIES_DIR
        self.people_dir = settings.SCRAPING_PEOPLE_DIR
        self.logs_dir = settings.SCRAPING_LOGS_DIR
        self.reports_dir = settings.SCRAPING_REPORTS_DIR
        for d in (self.companies_dir, self.people_dir, self.logs_dir, self.reports_dir):
            d.mkdir(parents=True, exist_ok=True)

    def write_companies(
        self,
        companies: List[CanonicalCompany],
        filename: str = "scraped_companies.json",
        include_personal_contacts: Optional[bool] = None,
    ) -> Path:
        """Writes scraped company records to output/scraping/companies/scraped_companies.json."""
        target_path = self.companies_dir / filename
        include_contacts = (
            include_personal_contacts
            if include_personal_contacts is not None
            else settings.ENABLE_PERSONAL_CONTACT_FIELDS
        )

        records = []
        for idx, c in enumerate(companies, 1):
            val_flags = get_company_validation_flags(c)
            records.append(
                c.to_channel_dict(
                    ingestion_method="scraping",
                    record_index=idx,
                    validation_flags=val_flags,
                    include_personal_contacts=include_contacts,
                )
            )

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)

        logger.info("Generated Scraped companies JSON", path=str(target_path), count=len(records))
        return target_path

    def write_people(
        self,
        people: List[DecisionMaker],
        filename: str = "scraped_people.json",
        company_rfc_map: Optional[Dict[str, str]] = None,
        include_personal_contacts: Optional[bool] = None,
    ) -> Path:
        """Writes scraped decision-maker records to output/scraping/people/scraped_people.json."""
        target_path = self.people_dir / filename
        include_contacts = (
            include_personal_contacts
            if include_personal_contacts is not None
            else settings.ENABLE_PERSONAL_CONTACT_FIELDS
        )
        rfc_map = company_rfc_map or {}

        records = []
        for idx, p in enumerate(people, 1):
            val_flags = get_person_validation_flags(p)
            comp_rfc = rfc_map.get(p.company_id)
            records.append(
                p.to_channel_dict(
                    ingestion_method="scraping",
                    record_index=idx,
                    company_rfc=comp_rfc,
                    validation_flags=val_flags,
                    include_personal_contacts=include_contacts,
                )
            )

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)

        logger.info("Generated Scraped people JSON", path=str(target_path), count=len(records))
        return target_path

    def write_summary(self, summary_data: Dict[str, Any], filename: str = "scraping_summary.json") -> Path:
        """Writes machine-readable Scraping summary to output/scraping/logs/scraping_summary.json."""
        target_path = self.logs_dir / filename
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2, ensure_ascii=False)
        return target_path

    def write_validation_report(self, report_data: Dict[str, Any], filename: str = "scraping_validation_report.json") -> Path:
        """Writes Scraping validation report to output/scraping/reports/scraping_validation_report.json."""
        target_path = self.reports_dir / filename
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)
        return target_path


class CombinedOutputManager:
    """Manages writing optional combined master exports merging API and Scraped datasets."""

    def __init__(self):
        self.companies_dir = settings.COMBINED_COMPANIES_DIR
        self.people_dir = settings.COMBINED_PEOPLE_DIR
        self.reports_dir = settings.COMBINED_REPORTS_DIR
        for d in (self.companies_dir, self.people_dir, self.reports_dir):
            d.mkdir(parents=True, exist_ok=True)

    def write_companies(
        self,
        companies: List[CanonicalCompany],
        filename: str = "all_companies.json",
        include_personal_contacts: Optional[bool] = None,
    ) -> Path:
        """Writes combined Golden Company profiles to output/combined/companies/all_companies.json."""
        target_path = self.companies_dir / filename
        include_contacts = (
            include_personal_contacts
            if include_personal_contacts is not None
            else settings.ENABLE_PERSONAL_CONTACT_FIELDS
        )

        data = [c.to_dict(include_personal_contacts=include_contacts) for c in companies]
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info("Generated Combined all_companies JSON", path=str(target_path), count=len(companies))
        return target_path

    def write_people(
        self,
        people: List[DecisionMaker],
        filename: str = "all_people.json",
        include_personal_contacts: Optional[bool] = None,
    ) -> Path:
        """Writes combined decision-maker leads to output/combined/people/all_people.json."""
        target_path = self.people_dir / filename
        include_contacts = (
            include_personal_contacts
            if include_personal_contacts is not None
            else settings.ENABLE_PERSONAL_CONTACT_FIELDS
        )

        data = [p.to_dict(include_personal_contacts=include_contacts) for p in people]
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info("Generated Combined all_people JSON", path=str(target_path), count=len(people))
        return target_path

    def write_summary(self, summary_data: Dict[str, Any], filename: str = "combined_summary.json") -> Path:
        """Writes combined summary report to output/combined/reports/combined_summary.json."""
        target_path = self.reports_dir / filename
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2, ensure_ascii=False)
        return target_path


class OutputManager:
    """Legacy and general output manager preserving Excel and backward compatibility."""

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or settings.OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.api = ApiOutputManager()
        self.scraping = ScrapingOutputManager()
        self.combined = CombinedOutputManager()

    def write_json(self, companies: List[CanonicalCompany], filename: str = "mexico_companies.json", include_personal_contacts: Optional[bool] = None) -> Path:
        target_path = self.output_dir / filename
        include_contacts = include_personal_contacts if include_personal_contacts is not None else settings.ENABLE_PERSONAL_CONTACT_FIELDS
        data = [c.to_dict(include_personal_contacts=include_contacts) for c in companies]
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return target_path

    def write_csv(self, companies: List[CanonicalCompany], filename: str = "mexico_companies.csv", include_personal_contacts: Optional[bool] = None) -> Path:
        target_path = self.output_dir / filename
        include_contacts = include_personal_contacts if include_personal_contacts is not None else settings.ENABLE_PERSONAL_CONTACT_FIELDS
        flat_rows = [c.to_flat_dict(include_personal_contacts=include_contacts) for c in companies]
        if not flat_rows:
            flat_rows = [{}]
        fieldnames = list(flat_rows[0].keys()) if flat_rows else []
        with open(target_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            if companies:
                writer.writerows(flat_rows)
        return target_path

    def write_xlsx(self, companies: List[CanonicalCompany], filename: str = "mexico_companies.xlsx", include_personal_contacts: Optional[bool] = None) -> Path:
        target_path = self.output_dir / filename
        include_contacts = include_personal_contacts if include_personal_contacts is not None else settings.ENABLE_PERSONAL_CONTACT_FIELDS
        wb = openpyxl.Workbook()
        ws_data = wb.active
        ws_data.title = "Companies"
        flat_rows = [c.to_flat_dict(include_personal_contacts=include_contacts) for c in companies]
        if not flat_rows:
            wb.save(target_path)
            return target_path
        headers = list(flat_rows[0].keys())
        header_fill = PatternFill(start_color="1A365D", end_color="1A365D", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        border_thin = Border(left=Side(style='thin', color='E2E8F0'), right=Side(style='thin', color='E2E8F0'), top=Side(style='thin', color='E2E8F0'), bottom=Side(style='thin', color='E2E8F0'))
        for col_num, header in enumerate(headers, 1):
            cell = ws_data.cell(row=1, column=col_num, value=header.replace("_", " ").title())
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
        for row_num, row_data in enumerate(flat_rows, 2):
            for col_num, header in enumerate(headers, 1):
                cell = ws_data.cell(row=row_num, column=col_num, value=row_data.get(header, ""))
                cell.border = border_thin
        for col_num, header in enumerate(headers, 1):
            sample_vals = [len(str(row.get(header, ""))) for row in flat_rows[:100]]
            max_len = max([len(header)] + sample_vals) if sample_vals else len(header)
            col_letter = openpyxl.utils.get_column_letter(col_num)
            ws_data.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 50)
        wb.save(target_path)
        return target_path

    def write_people_json(self, people: List[Any], filename: str = "mexico_people.json", include_personal_contacts: Optional[bool] = None) -> Path:
        target_path = self.output_dir / filename
        include_contacts = include_personal_contacts if include_personal_contacts is not None else settings.ENABLE_PERSONAL_CONTACT_FIELDS
        data = [p.to_dict(include_personal_contacts=include_contacts) for p in people]
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return target_path

    def write_people_csv(self, people: List[Any], filename: str = "mexico_people.csv", include_personal_contacts: Optional[bool] = None) -> Path:
        target_path = self.output_dir / filename
        include_contacts = include_personal_contacts if include_personal_contacts is not None else settings.ENABLE_PERSONAL_CONTACT_FIELDS
        flat_rows = [p.to_flat_dict(include_personal_contacts=include_contacts) for p in people]
        if not flat_rows:
            flat_rows = [{}]
        fieldnames = list(flat_rows[0].keys()) if flat_rows else []
        with open(target_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            if people:
                writer.writerows(flat_rows)
        return target_path

    def write_people_xlsx(self, people: List[Any], filename: str = "mexico_people.xlsx", include_personal_contacts: Optional[bool] = None) -> Path:
        target_path = self.output_dir / filename
        include_contacts = include_personal_contacts if include_personal_contacts is not None else settings.ENABLE_PERSONAL_CONTACT_FIELDS
        wb = openpyxl.Workbook()
        ws_data = wb.active
        ws_data.title = "Decision Makers"
        flat_rows = [p.to_flat_dict(include_personal_contacts=include_contacts) for p in people]
        if not flat_rows:
            wb.save(target_path)
            return target_path
        headers = list(flat_rows[0].keys())
        header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        border_thin = Border(left=Side(style='thin', color='E2E8F0'), right=Side(style='thin', color='E2E8F0'), top=Side(style='thin', color='E2E8F0'), bottom=Side(style='thin', color='E2E8F0'))
        for col_num, header in enumerate(headers, 1):
            cell = ws_data.cell(row=1, column=col_num, value=header.replace("_", " ").title())
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
        for row_num, row_data in enumerate(flat_rows, 2):
            for col_num, header in enumerate(headers, 1):
                cell = ws_data.cell(row=row_num, column=col_num, value=row_data.get(header, ""))
                cell.border = border_thin
        for col_num, header in enumerate(headers, 1):
            sample_vals = [len(str(row.get(header, ""))) for row in flat_rows[:100]]
            max_len = max([len(header)] + sample_vals) if sample_vals else len(header)
            col_letter = openpyxl.utils.get_column_letter(col_num)
            ws_data.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 45)
        wb.save(target_path)
        return target_path

    def write_combined_master_export(self, companies: List[CanonicalCompany], filename_csv: str = "mexico_master_combined.csv", filename_xlsx: str = "mexico_master_combined.xlsx", include_personal_contacts: Optional[bool] = None) -> Dict[str, Path]:
        include_contacts = include_personal_contacts if include_personal_contacts is not None else settings.ENABLE_PERSONAL_CONTACT_FIELDS
        combined_rows = []
        for c in companies:
            c_dict = c.to_flat_dict(include_personal_contacts=include_contacts)
            primary_dm = c.decision_makers[0] if c.decision_makers else None
            row = {
                "company_id": c.company_id,
                "legal_name": c.legal_name or "",
                "trade_name": c.trade_name or "",
                "rfc": c.rfc or "",
                "rfc_type": c.rfc_type or "",
                "industry": c.industry or "",
                "industry_code": c.industry_code or "",
                "employee_count_min": c.employee_count_min if c.employee_count_min is not None else "",
                "employee_count_max": c.employee_count_max if c.employee_count_max is not None else "",
                "website": c.website or "",
                "domain": c.domain or "",
                "company_phone": c_dict.get("phone", ""),
                "company_email": c_dict.get("email", ""),
                "street": c_dict.get("street", ""),
                "number": c_dict.get("number", ""),
                "colony": c_dict.get("colony", ""),
                "municipality": c_dict.get("municipality", ""),
                "state": c_dict.get("state", ""),
                "postal_code": c_dict.get("postal_code", ""),
                "country": c_dict.get("country", "Mexico"),
                "latitude": c_dict.get("latitude", ""),
                "longitude": c_dict.get("longitude", ""),
                "executive_name": primary_dm.full_name if primary_dm else "",
                "executive_title": primary_dm.title if primary_dm else "",
                "standardized_title": primary_dm.standardized_title if primary_dm else "",
                "seniority_level": primary_dm.seniority_level if primary_dm else "",
                "department": primary_dm.department if primary_dm else "",
                "executive_work_email": (primary_dm.work_email if include_contacts else "") if primary_dm else "",
                "email_status": primary_dm.email_status if primary_dm else "",
                "executive_phone": (primary_dm.direct_phone if include_contacts else "") if primary_dm else "",
                "all_sources_combined": c_dict.get("sources", ""),
                "source_count": c.source_count or len(c.source_records),
                "data_quality_score": c.data_quality_score,
                "last_verified_at": c.last_verified_at or "",
            }
            combined_rows.append(row)
        if not combined_rows:
            combined_rows = [{}]
        fieldnames = list(combined_rows[0].keys())
        target_csv = self.output_dir / filename_csv
        with open(target_csv, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            if companies:
                writer.writerows(combined_rows)
        target_xlsx = self.output_dir / filename_xlsx
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Master Combined Directory"
        header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        border_thin = Border(left=Side(style='thin', color='E2E8F0'), right=Side(style='thin', color='E2E8F0'), top=Side(style='thin', color='E2E8F0'), bottom=Side(style='thin', color='E2E8F0'))
        for col_num, header in enumerate(fieldnames, 1):
            cell = ws.cell(row=1, column=col_num, value=header.replace("_", " ").title())
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
        for row_num, row_data in enumerate(combined_rows, 2):
            for col_num, header in enumerate(fieldnames, 1):
                cell = ws.cell(row=row_num, column=col_num, value=row_data.get(header, ""))
                cell.border = border_thin
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col[:1000])
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 45)
        wb.save(target_xlsx)
        return {"csv": target_csv, "xlsx": target_xlsx}

    def write_validation_report(self, report_data: Dict[str, Any], filename: str = "validation_report.json") -> Path:
        target_path = self.output_dir / filename
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)
        return target_path

    def write_source_status(self, source_statuses: Dict[str, Any], filename: str = "source_status.json") -> Path:
        target_path = self.output_dir / filename
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(source_statuses, f, indent=2, ensure_ascii=False)
        return target_path


output_manager = OutputManager()
api_output_manager = ApiOutputManager()
scraping_output_manager = ScrapingOutputManager()
combined_output_manager = CombinedOutputManager()
