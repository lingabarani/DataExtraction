"""
Abstract base connector for Mexican open-data ingestion sources.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from ..config.sources import SourceConfig
from ..models.company import CanonicalCompany
from ..models.source_record import RawSourcePayload, SourceProvenanceRecord
from ..pipeline.validation import validate_company, ValidationResult
from ..utils.logging import logger
from ..utils.http import HttpClient


class SourceConnector(ABC):
    """Base interface for all Mexican open-data connectors."""

    def __init__(self, config: SourceConfig):
        self.config = config
        self.http_client = HttpClient(
            timeout=30,
            max_retries=3,
            backoff_factor=2.0,
        )

    @abstractmethod
    def fetch(self, limit: Optional[int] = None) -> List[RawSourcePayload]:
        """Fetches raw data payloads from the source (API, CSV stream, or file)."""
        pass

    @abstractmethod
    def parse(self, payload: RawSourcePayload) -> Dict[str, Any]:
        """Parses a raw payload dictionary into an intermediate key-value map."""
        pass

    @abstractmethod
    def normalize(self, parsed: Dict[str, Any], provenance: SourceProvenanceRecord) -> CanonicalCompany:
        """Transforms parsed data into a normalized CanonicalCompany instance."""
        pass

    def validate(self, company: CanonicalCompany) -> ValidationResult:
        """Validates normalized company record."""
        return validate_company(company)

    def ingest(self, limit: Optional[int] = None) -> Tuple[List[CanonicalCompany], List[Dict[str, Any]]]:
        """
        Executes complete ingestion lifecycle for this connector:
        Fetch -> Parse -> Normalize -> Validate.
        
        Returns:
            (valid_companies, invalid_records_report)
        """
        logger.info(f"Starting ingestion for source {self.config.name}", limit=limit)
        raw_payloads = self.fetch(limit=limit)
        
        valid_companies: List[CanonicalCompany] = []
        invalid_records: List[Dict[str, Any]] = []

        for payload in raw_payloads:
            try:
                parsed = self.parse(payload)
                provenance = SourceProvenanceRecord(
                    source=self.config.name,
                    source_record_id=str(payload.source_record_id),
                    source_url=payload.source_url,
                    retrieved_at=payload.retrieved_at,
                    raw_hash=payload.raw_hash,
                    raw_payload_data=payload.raw_data,
                )
                company = self.normalize(parsed, provenance)
                val_result = self.validate(company)

                if val_result.is_valid:
                    valid_companies.append(company)
                else:
                    invalid_records.append({
                        "source": self.config.name,
                        "source_record_id": payload.source_record_id,
                        "errors": val_result.errors,
                        "warnings": val_result.warnings,
                        "raw_data": payload.raw_data,
                    })
            except Exception as e:
                logger.error(
                    f"Error processing record from {self.config.name}",
                    record_id=payload.source_record_id,
                    error=str(e),
                )
                invalid_records.append({
                    "source": self.config.name,
                    "source_record_id": payload.source_record_id,
                    "errors": [f"PROCESSING_EXCEPTION: {str(e)}"],
                    "warnings": [],
                    "raw_data": payload.raw_data,
                })

        logger.info(
            f"Ingestion completed for {self.config.name}",
            valid_records=len(valid_companies),
            invalid_records=len(invalid_records),
        )

        return valid_companies, invalid_records
