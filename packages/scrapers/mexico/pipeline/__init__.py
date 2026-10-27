"""
Pipeline package.
"""

from .normalization import (
    normalize_company_name,
    normalize_email,
    normalize_website,
    parse_employee_range,
)
from .validation import validate_company, ValidationResult
from .quality import calculate_data_quality_score
from .entity_resolution import entity_resolver, MatchResult
from .deduplication import deduplication_engine
from .merger import merge_engine
from .person_enrichment import person_enrichment_engine, classify_title
