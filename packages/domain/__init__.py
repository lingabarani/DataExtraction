"""
DataExtraction — Enterprise Business Domain Package
===================================================
Exports core enterprise domain capabilities:
  - normalizer: Data cleaning, unicode transforms, and legal suffix stripping
  - validation: 5-tier contact, statutory tax, and geospatial validation
  - deduplication: Multi-strategy deduplication and entity resolution
  - splink_engine: Mathematical record linkage with Fellegi-Sunter weights
  - lead_builder: Golden record construction and conflict resolution
  - gleif_enricher: Global Legal Entity Identifier (GLEIF) foundation
"""

from packages.domain.normalizer import (
    clean_legal_suffixes,
    clean_domain,
    clean_string,
    normalize_company,
    normalize_person,
    to_int,
    to_float,
    to_bool,
)
from packages.domain.validation import (
    extract_registered_domain,
    validate_email,
    validate_phone,
    normalise_linkedin,
    validate_contact,
    contact_is_usable,
    lead_score_from_contact,
    validate_ein,
    validate_rfc,
    validate_tax_id,
    normalize_postal_code,
    validate_coordinates,
)
from packages.domain.deduplication import (
    Deduplicator,
    DedupResult,
)
from packages.domain.splink_engine import (
    SplinkIdentityLinker,
    SplinkEngine,
    splink_linker,
    splink_engine,
)
from packages.domain.lead_builder import (
    build_us_lead,
    build_mexico_lead,
)
from packages.domain.gleif_enricher import (
    GLEIFEnricher,
    gleif_enricher,
    validate_lei_checksum,
)
from packages.domain.smtp_engine import (
    get_mx_hosts,
    is_catchall_domain,
    verify_email_smtp,
    generate_candidate_emails,
)
from packages.domain.email_enricher import (
    rank_emails,
    compute_email_confidence,
    EmailEnrichmentEngine,
    email_enrichment_engine,
    EmailCandidate,
    EnrichmentResult,
)

__all__ = [
    # Normalizer
    "clean_legal_suffixes",
    "clean_domain",
    "clean_string",
    "normalize_company",
    "normalize_person",
    "to_int",
    "to_float",
    "to_bool",
    # Validation
    "extract_registered_domain",
    "validate_email",
    "validate_phone",
    "normalise_linkedin",
    "validate_contact",
    "contact_is_usable",
    "lead_score_from_contact",
    "validate_ein",
    "validate_rfc",
    "validate_tax_id",
    "normalize_postal_code",
    "validate_coordinates",
    # Deduplication
    "Deduplicator",
    "DedupResult",
    # Splink Linkage
    "SplinkIdentityLinker",
    "SplinkEngine",
    "splink_linker",
    "splink_engine",
    # Lead Builder
    "build_us_lead",
    "build_mexico_lead",
    # GLEIF
    "GLEIFEnricher",
    "gleif_enricher",
    "validate_lei_checksum",
    # Email Enrichment & SMTP Engine
    "get_mx_hosts",
    "is_catchall_domain",
    "verify_email_smtp",
    "generate_candidate_emails",
    "rank_emails",
    "compute_email_confidence",
    "EmailEnrichmentEngine",
    "email_enrichment_engine",
    "EmailCandidate",
    "EnrichmentResult",
]

