#!/usr/bin/env python3
"""
SEC EDGAR Public Company Data Scraper.

Collects publicly available company information directly from the official SEC EDGAR system.
Strict adherence to:
- Official SEC fair access policy (<= 10 requests/second, declared User-Agent with contact email)
- Free public government data only (No paid APIs)
- Retry handling with exponential backoff on HTTP 429/5xx errors
- Pagination support for companies and filings
- Checkpointing and resume capability for large/complete datasets
- Support for official SEC Bulk Archive (submissions.zip ~1.5 GB for all 600,000+ entities)
- Raw data preservation in data/raw/sec/
"""

import argparse
import json
import logging
import os
import sys
import time
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, Set, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("SECScraper")


class SECScraper:
    """
    Scraper for official SEC EDGAR public company filings and metadata.
    """

    TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
    SUBMISSION_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
    BULK_SUBMISSIONS_URL = "https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip"
    ARCHIVES_BASE_URL = "https://www.sec.gov/Archives/edgar/data"

    def __init__(
        self,
        user_agent: str = "USBusinessDataCollector/1.0 (compliance@usbusinessdata.org)",
        rate_limit_delay: float = 0.2,  # 5 requests/sec, well within SEC's 10 req/s limit
        max_retries: int = 5,
        backoff_factor: float = 1.0,
        raw_output_dir: str = "data/raw/sec"
    ):
        """
        Initialize the SEC EDGAR Scraper.

        :param user_agent: User-Agent header declared per SEC access guidelines.
        :param rate_limit_delay: Minimum delay in seconds between successive requests.
        :param max_retries: Maximum number of retries for transient network/server errors.
        :param backoff_factor: Multiplier for exponential backoff on retries.
        :param raw_output_dir: Output directory where raw JSON files are saved.
        """
        self.user_agent = user_agent
        self.rate_limit_delay = rate_limit_delay
        self.raw_output_dir = raw_output_dir
        self._last_request_time = 0.0
        self._cached_tickers: Optional[List[Dict[str, Any]]] = None

        # Ensure raw output directory exists
        os.makedirs(self.raw_output_dir, exist_ok=True)

        # Setup persistent requests session with retry adapter
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate"
        })

        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _throttle(self):
        """Enforce rate limits per SEC fair access guidelines."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    def _get(self, url: str, timeout: int = 20, stream: bool = False) -> Optional[requests.Response]:
        """
        Perform a rate-limited GET request with error handling and backoff.
        """
        self._throttle()
        try:
            resp = self.session.get(url, timeout=timeout, stream=stream)
            if resp.status_code == 200:
                return resp
            elif resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                sleep_duration = float(retry_after) if retry_after else 2.0
                logger.warning(f"SEC 429 rate limit encountered. Waiting {sleep_duration}s...")
                time.sleep(sleep_duration)
                return self._get(url, timeout=timeout, stream=stream)
            else:
                logger.warning(f"SEC request to {url} returned HTTP {resp.status_code}")
                return resp
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error requesting {url}: {e}")
            return None

    def get_all_company_tickers(self) -> List[Dict[str, Any]]:
        """
        Fetch and cache the full master list of companies indexed by SEC EDGAR (~10,422 companies).
        Returns a list of dicts with keys: 'cik_str', 'ticker', 'title'.
        """
        if self._cached_tickers is not None:
            return self._cached_tickers

        logger.info(f"Fetching master company tickers from SEC: {self.TICKERS_URL}")
        resp = self._get(self.TICKERS_URL, timeout=20)
        if resp and resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict):
                self._cached_tickers = list(data.values())
            elif isinstance(data, list):
                self._cached_tickers = data
            else:
                self._cached_tickers = []
            logger.info(f"Loaded {len(self._cached_tickers)} companies from SEC EDGAR tickers.")
        else:
            logger.error("Failed to load company tickers from SEC EDGAR.")
            self._cached_tickers = []

        return self._cached_tickers

    def get_company_submission(self, cik: str or int) -> Optional[Dict[str, Any]]:
        """
        Fetch the raw company submission data from SEC EDGAR for a given CIK.
        CIK is zero-padded to 10 digits as required by SEC API.
        """
        cik_padded = str(cik).strip().zfill(10)
        url = self.SUBMISSION_URL.format(cik=cik_padded)
        resp = self._get(url, timeout=20)
        if resp and resp.status_code == 200:
            try:
                return resp.json()
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON for CIK {cik_padded}: {e}")
                return None
        return None

    def get_additional_filings_page(self, cik: str or int, file_name: str) -> Optional[Dict[str, Any]]:
        """
        Fetch an older filings pagination page if listed in filings.files.
        """
        url = f"https://data.sec.gov/submissions/{file_name}"
        resp = self._get(url, timeout=20)
        if resp and resp.status_code == 200:
            try:
                return resp.json()
            except json.JSONDecodeError:
                return None
        return None

    def _extract_filing_information(
        self,
        raw_submission: Dict[str, Any],
        cik_padded: str,
        max_filings: int = 10,
        include_paginated_filings: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Parse recent filings into structured list of filing records.
        """
        filings_list: List[Dict[str, Any]] = []
        filings_data = raw_submission.get("filings", {})
        recent = filings_data.get("recent", {})

        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        report_dates = recent.get("reportDate", [])
        primary_docs = recent.get("primaryDocument", [])
        doc_descs = recent.get("primaryDocDescription", [])
        act_list = recent.get("act", [])
        size_list = recent.get("size", [])

        total_recent = len(forms)
        cik_int = int(cik_padded)

        for i in range(min(total_recent, max_filings)):
            acc = accessions[i] if i < len(accessions) else ""
            acc_no_hyphen = acc.replace("-", "")
            pdoc = primary_docs[i] if i < len(primary_docs) else ""
            
            doc_url = ""
            if acc and pdoc:
                doc_url = f"{self.ARCHIVES_BASE_URL}/{cik_int}/{acc_no_hyphen}/{pdoc}"

            filings_list.append({
                "form": forms[i] if i < len(forms) else "",
                "filing_date": filing_dates[i] if i < len(filing_dates) else "",
                "report_date": report_dates[i] if i < len(report_dates) else "",
                "accession_number": acc,
                "act": act_list[i] if i < len(act_list) else "",
                "file_size": size_list[i] if i < len(size_list) else None,
                "primary_document": pdoc,
                "document_url": doc_url,
                "description": doc_descs[i] if i < len(doc_descs) else ""
            })

        # Check if pagination files are present and requested
        if include_paginated_filings and len(filings_list) < max_filings:
            files = filings_data.get("files", [])
            for file_entry in files:
                file_name = file_entry.get("name")
                if not file_name:
                    continue
                older_data = self.get_additional_filings_page(cik_padded, file_name)
                if not older_data:
                    continue
                old_forms = older_data.get("form", [])
                old_dates = older_data.get("filingDate", [])
                old_accs = older_data.get("accessionNumber", [])
                old_pdocs = older_data.get("primaryDocument", [])
                for j in range(len(old_forms)):
                    if len(filings_list) >= max_filings:
                        break
                    acc = old_accs[j] if j < len(old_accs) else ""
                    acc_no_hyphen = acc.replace("-", "")
                    pdoc = old_pdocs[j] if j < len(old_pdocs) else ""
                    doc_url = f"{self.ARCHIVES_BASE_URL}/{cik_int}/{acc_no_hyphen}/{pdoc}" if acc and pdoc else ""
                    filings_list.append({
                        "form": old_forms[j],
                        "filing_date": old_dates[j] if j < len(old_dates) else "",
                        "report_date": "",
                        "accession_number": acc,
                        "primary_document": pdoc,
                        "document_url": doc_url,
                        "description": ""
                    })
                if len(filings_list) >= max_filings:
                    break

        return filings_list

    def extract_company_record(
        self,
        raw_submission: Dict[str, Any],
        fallback_title: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Map SEC EDGAR submission JSON to the target fields:
        - company_name
        - legal_name
        - CIK
        - SIC
        - industry
        - state
        - city
        - ZIP
        - business_address
        - state_of_incorporation
        - company_description
        - website
        - filing_information
        - source_url
        - source_record_id
        - collected_at
        """
        cik_raw = raw_submission.get("cik")
        cik = str(cik_raw).strip().zfill(10) if cik_raw else ""
        source_url = self.SUBMISSION_URL.format(cik=cik)

        # Names
        legal_name = (raw_submission.get("name") or fallback_title or "").strip()
        company_name = legal_name

        # Industry / SIC
        sic = str(raw_submission.get("sic") or "").strip()
        industry = (raw_submission.get("sicDescription") or "").strip()

        # Addresses
        addresses = raw_submission.get("addresses", {}) or {}
        biz_addr = addresses.get("business") or {}
        mailing_addr = addresses.get("mailing") or {}

        # Prefer business address, fallback to mailing address
        active_addr = biz_addr if (biz_addr.get("city") or biz_addr.get("street1")) else mailing_addr

        street1 = (active_addr.get("street1") or "").strip()
        street2 = (active_addr.get("street2") or "").strip()
        city = (active_addr.get("city") or "").strip()
        state = (active_addr.get("stateOrCountry") or active_addr.get("stateOrCountryDescription") or "").strip()
        zip_code = (active_addr.get("zipCode") or "").strip()

        # Format full business address string
        street_parts = [s for s in [street1, street2] if s]
        address_parts = []
        if street_parts:
            address_parts.append(" ".join(street_parts))
        if city:
            address_parts.append(city)
        if state and zip_code:
            address_parts.append(f"{state} {zip_code}")
        elif state:
            address_parts.append(state)
        elif zip_code:
            address_parts.append(zip_code)

        business_address = ", ".join(address_parts) if address_parts else None

        # State of incorporation
        state_of_incorporation = (
            raw_submission.get("stateOfIncorporation")
            or raw_submission.get("stateOfIncorporationDescription")
            or ""
        ).strip()

        # Company description & website
        company_description = (raw_submission.get("description") or "").strip()
        website = (raw_submission.get("website") or raw_submission.get("investorWebsite") or "").strip()

        # Filings
        filing_information = self._extract_filing_information(raw_submission, cik, max_filings=10)

        # Timestamp
        collected_at = datetime.now(timezone.utc).isoformat()

        record = {
            "company_name": company_name,
            "legal_name": legal_name,
            "CIK": cik,
            "SIC": sic,
            "industry": industry,
            "state": state,
            "city": city,
            "ZIP": zip_code,
            "business_address": business_address,
            "state_of_incorporation": state_of_incorporation,
            "company_description": company_description,
            "website": website,
            "filing_information": filing_information,
            "source_url": source_url,
            "source_record_id": cik,
            "collected_at": collected_at
        }

        return record

    def _load_existing_ciks(self, jsonl_path: str) -> Set[str]:
        """Load already extracted CIKs to support resuming interrupted jobs."""
        seen = set()
        if os.path.exists(jsonl_path):
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            obj = json.loads(line)
                            if "CIK" in obj:
                                seen.add(obj["CIK"])
                        except json.JSONDecodeError:
                            continue
        return seen

    def scrape_companies(
        self,
        limit: Optional[int] = 10,
        ciks: Optional[List[str or int]] = None,
        tickers: Optional[List[str]] = None,
        name_filter: Optional[str] = None,
        page: int = 1,
        page_size: Optional[int] = None,
        scrape_all: bool = False,
        resume: bool = True
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Scrape public company data from SEC EDGAR with resume & streaming capability.

        :param limit: Number of companies to collect. If None or scrape_all=True, collects all.
        :param ciks: Optional specific list of CIK identifiers to collect.
        :param tickers: Optional specific list of stock tickers (e.g. ['AAPL', 'MSFT']).
        :param name_filter: Substring to filter company titles.
        :param page: 1-indexed page number for pagination.
        :param page_size: Size of each page (defaults to limit).
        :param scrape_all: Scrape all matched companies.
        :param resume: Skip already scraped companies in master JSONL file.
        :return: (extracted_records, run_stats)
        """
        start_time = time.time()
        extracted_records: List[Dict[str, Any]] = []
        raw_submissions: List[Dict[str, Any]] = []
        failed_count = 0

        # Master output paths
        stream_jsonl_path = os.path.join(self.raw_output_dir, "sec_companies_master.jsonl")
        completed_ciks = self._load_existing_ciks(stream_jsonl_path) if resume else set()
        if completed_ciks:
            logger.info(f"Resume active: {len(completed_ciks)} CIKs already saved in {stream_jsonl_path}.")

        # Determine target list of (cik, fallback_title)
        targets: List[Tuple[str, str]] = []

        if ciks:
            targets = [(str(c).strip().zfill(10), "") for c in ciks]
        else:
            all_tickers = self.get_all_company_tickers()
            tickers_set = set([t.upper() for t in tickers]) if tickers else None
            filter_str = name_filter.lower().strip() if name_filter else None

            filtered = []
            for item in all_tickers:
                c_str = str(item.get("cik_str", "")).zfill(10)
                ticker = item.get("ticker", "").upper()
                title = item.get("title", "")

                if tickers_set and ticker not in tickers_set:
                    continue
                if filter_str and filter_str not in title.lower() and filter_str != ticker.lower():
                    continue

                filtered.append((c_str, title))

            if scrape_all:
                targets = filtered
            else:
                eff_page_size = page_size or (limit if limit is not None else 10)
                offset = (page - 1) * eff_page_size
                effective_limit = limit if limit is not None else len(filtered)
                targets = filtered[offset: offset + effective_limit]

        total_targets = len(targets)
        # Filter out already completed if resume is enabled
        pending_targets = [t for t in targets if t[0] not in completed_ciks]
        already_done = total_targets - len(pending_targets)

        logger.info(f"Targeting {total_targets} companies (Pending: {len(pending_targets)}, Already scraped: {already_done}).")

        # Open stream file in append mode
        with open(stream_jsonl_path, "a", encoding="utf-8") as stream_f:
            for idx, (cik, title) in enumerate(pending_targets, 1):
                progress_pct = round((idx / len(pending_targets)) * 100, 1)
                logger.info(f"[{idx}/{len(pending_targets)}] ({progress_pct}%) Scraping CIK: {cik} ({title or 'N/A'})")
                
                raw_sub = self.get_company_submission(cik)
                if not raw_sub:
                    logger.warning(f"Failed to fetch or parse submission for CIK {cik}")
                    failed_count += 1
                    continue

                raw_submissions.append(raw_sub)

                try:
                    record = self.extract_company_record(raw_sub, fallback_title=title)
                    extracted_records.append(record)
                    # Write immediately to JSONL for checkpoint safety
                    stream_f.write(json.dumps(record) + "\n")
                    stream_f.flush()
                except Exception as e:
                    logger.error(f"Error extracting fields for CIK {cik}: {e}", exc_info=True)
                    failed_count += 1

        execution_time = round(time.time() - start_time, 2)

        # Save batch run files
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        raw_file_path = os.path.join(self.raw_output_dir, f"raw_sec_submissions_{timestamp_str}.json")
        extracted_file_path = os.path.join(self.raw_output_dir, f"extracted_sec_companies_{timestamp_str}.json")

        if raw_submissions:
            try:
                with open(raw_file_path, "w", encoding="utf-8") as f:
                    json.dump(raw_submissions, f, indent=2)
                with open(extracted_file_path, "w", encoding="utf-8") as f:
                    json.dump(extracted_records, f, indent=2)
            except Exception as e:
                logger.error(f"Failed to save batch JSON files: {e}")

        stats = {
            "records_found": total_targets,
            "records_extracted": len(extracted_records),
            "records_previously_scraped": already_done,
            "records_failed": failed_count,
            "execution_time": f"{execution_time} seconds",
            "master_jsonl": stream_jsonl_path,
            "batch_raw_file": raw_file_path if raw_submissions else None,
            "batch_extracted_file": extracted_file_path if extracted_records else None,
            "sample_record": extracted_records[0] if extracted_records else None
        }

        return extracted_records, stats

    def download_and_extract_bulk_archive(
        self,
        dest_zip: Optional[str] = None,
        extract_to: Optional[str] = None,
        max_extract_count: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Download and extract the official SEC EDGAR bulk submissions archive (submissions.zip ~1.5 GB).
        Contains the complete submission JSON for ALL 600,000+ SEC-registered companies/entities.
        """
        zip_path = dest_zip or os.path.join(self.raw_output_dir, "submissions.zip")
        extract_dir = extract_to or os.path.join(self.raw_output_dir, "bulk_submissions")
        os.makedirs(extract_dir, exist_ok=True)

        start_time = time.time()
        logger.info(f"Connecting to SEC Bulk Archive: {self.BULK_SUBMISSIONS_URL}")

        if not os.path.exists(zip_path):
            resp = self._get(self.BULK_SUBMISSIONS_URL, stream=True, timeout=60)
            if not resp or resp.status_code != 200:
                raise RuntimeError(f"Failed to download bulk submissions.zip: HTTP {resp.status_code if resp else 'None'}")

            total_size = int(resp.headers.get("content-length", 0))
            logger.info(f"Downloading submissions.zip ({round(total_size / (1024 * 1024), 1)} MB)...")
            
            downloaded = 0
            with open(zip_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):  # 1 MB chunks
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0 and downloaded % (50 * 1024 * 1024) < 1024 * 1024:
                            pct = round((downloaded / total_size) * 100, 1)
                            logger.info(f"Download progress: {pct}% ({round(downloaded / (1024*1024))} MB / {round(total_size / (1024*1024))} MB)")

            logger.info(f"Bulk download complete: {zip_path}")
        else:
            logger.info(f"Using existing bulk zip archive: {zip_path}")

        # Extract and parse
        extracted_records: List[Dict[str, Any]] = []
        master_jsonl = os.path.join(self.raw_output_dir, "sec_companies_master.jsonl")

        logger.info(f"Extracting submission files from {zip_path}...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            namelist = [name for name in zf.namelist() if name.startswith("CIK") and name.endswith(".json")]
            total_in_zip = len(namelist)
            logger.info(f"Archive contains {total_in_zip} CIK submission files.")

            target_files = namelist[:max_extract_count] if max_extract_count else namelist

            with open(master_jsonl, "a", encoding="utf-8") as out_f:
                for idx, fname in enumerate(target_files, 1):
                    if idx % 5000 == 0 or idx == len(target_files):
                        logger.info(f"Processed {idx}/{len(target_files)} entity files from bulk archive...")
                    try:
                        with zf.open(fname) as file_data:
                            raw_sub = json.load(file_data)
                            rec = self.extract_company_record(raw_sub)
                            out_f.write(json.dumps(rec) + "\n")
                            if len(extracted_records) < 10:
                                extracted_records.append(rec)
                    except Exception as e:
                        continue

        elapsed = round(time.time() - start_time, 2)
        return {
            "records_found": total_in_zip,
            "records_extracted": len(target_files),
            "execution_time": f"{elapsed} seconds",
            "master_jsonl": master_jsonl,
            "sample_record": extracted_records[0] if extracted_records else None
        }


def main():
    parser = argparse.ArgumentParser(description="SEC EDGAR Company Information Scraper")
    parser.add_argument("--all", action="store_true", help="Scrape all ~10,422 publicly traded companies via API")
    parser.add_argument("--bulk-download", action="store_true",
                        help="Download official SEC bulk archive (submissions.zip ~1.5 GB) for all 600k+ entities")
    parser.add_argument("--limit", type=int, default=5, help="Number of companies to collect (default: 5)")
    parser.add_argument("--tickers", nargs="+", help="Specific tickers to scrape (e.g. AAPL MSFT NVDA)")
    parser.add_argument("--ciks", nargs="+", help="Specific CIK numbers to scrape")
    parser.add_argument("--name", type=str, help="Search by company name substring")
    parser.add_argument("--page", type=int, default=1, help="Page number for pagination (default: 1)")
    parser.add_argument("--page-size", type=int, default=None, help="Page size for pagination")
    parser.add_argument("--no-resume", action="store_true", help="Do not resume; scrape from scratch")
    parser.add_argument("--output-dir", type=str, default="data/raw/sec", help="Directory to save raw results")
    parser.add_argument("--user-agent", type=str, default="USBusinessDataCollector/1.0 (compliance@usbusinessdata.org)",
                        help="Declared User-Agent header required by SEC")

    args = parser.parse_args()

    scraper = SECScraper(
        user_agent=args.user_agent,
        raw_output_dir=args.output_dir
    )

    if args.bulk_download:
        print("\n" + "=" * 60)
        print("          DOWNLOADING SEC EDGAR BULK ARCHIVE (~1.5 GB)          ")
        print("=" * 60)
        stats = scraper.download_and_extract_bulk_archive()
        print("\n" + "=" * 60)
        print("                 BULK EXTRACTION RESULTS                  ")
        print("=" * 60)
        print(f"records_found     : {stats['records_found']}")
        print(f"records_extracted : {stats['records_extracted']}")
        print(f"execution_time    : {stats['execution_time']}")
        print(f"master_jsonl      : {stats['master_jsonl']}")
        print("=" * 60 + "\n")
        return

    records, stats = scraper.scrape_companies(
        limit=None if args.all else args.limit,
        ciks=args.ciks,
        tickers=args.tickers,
        name_filter=args.name,
        page=args.page,
        page_size=args.page_size,
        scrape_all=args.all,
        resume=not args.no_resume
    )

    print("\n" + "=" * 60)
    print("                 SEC EDGAR SCRAPER RESULTS                 ")
    print("=" * 60)
    print(f"records_found     : {stats['records_found']}")
    print(f"records_extracted : {stats['records_extracted']}")
    print(f"records_failed    : {stats['records_failed']}")
    print(f"execution_time    : {stats['execution_time']}")
    print("-" * 60)
    print("sample_record:")
    if stats['sample_record']:
        print(json.dumps(stats['sample_record'], indent=2))
    else:
        print("None")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
