"""
DataExtraction — Enterprise Business Domain Package
===================================================
Lazily exports core enterprise domain capabilities via PEP 562 __getattr__
so importing a single lightweight submodule (e.g. validation or email_enricher)
never eagerly loads heavy analytical/scraping engines (pandas, splink, duckdb, botasaurus).
"""

import importlib

_SYMBOL_MAP = {
    # Normalizer
    "clean_legal_suffixes": ("packages.domain.normalizer", "clean_legal_suffixes"),
    "clean_domain": ("packages.domain.normalizer", "clean_domain"),
    "clean_string": ("packages.domain.normalizer", "clean_string"),
    "normalize_company": ("packages.domain.normalizer", "normalize_company"),
    "normalize_person": ("packages.domain.normalizer", "normalize_person"),
    "to_int": ("packages.domain.normalizer", "to_int"),
    "to_float": ("packages.domain.normalizer", "to_float"),
    "to_bool": ("packages.domain.normalizer", "to_bool"),
    # Validation
    "extract_registered_domain": ("packages.domain.validation", "extract_registered_domain"),
    "validate_email": ("packages.domain.validation", "validate_email"),
    "validate_phone": ("packages.domain.validation", "validate_phone"),
    "normalise_linkedin": ("packages.domain.validation", "normalise_linkedin"),
    "validate_contact": ("packages.domain.validation", "validate_contact"),
    "contact_is_usable": ("packages.domain.validation", "contact_is_usable"),
    "lead_score_from_contact": ("packages.domain.validation", "lead_score_from_contact"),
    "validate_ein": ("packages.domain.validation", "validate_ein"),
    "validate_rfc": ("packages.domain.validation", "validate_rfc"),
    "validate_tax_id": ("packages.domain.validation", "validate_tax_id"),
    "normalize_postal_code": ("packages.domain.validation", "normalize_postal_code"),
    "validate_coordinates": ("packages.domain.validation", "validate_coordinates"),
    # Deduplication
    "Deduplicator": ("packages.domain.deduplication", "Deduplicator"),
    "DedupResult": ("packages.domain.deduplication", "DedupResult"),
    # Splink Linkage
    "SplinkIdentityLinker": ("packages.domain.splink_engine", "SplinkIdentityLinker"),
    "SplinkEngine": ("packages.domain.splink_engine", "SplinkEngine"),
    "splink_linker": ("packages.domain.splink_engine", "splink_linker"),
    "splink_engine": ("packages.domain.splink_engine", "splink_engine"),
    # Lead Builder
    "build_us_lead": ("packages.domain.lead_builder", "build_us_lead"),
    "build_mexico_lead": ("packages.domain.lead_builder", "build_mexico_lead"),
    # GLEIF
    "GLEIFEnricher": ("packages.domain.gleif_enricher", "GLEIFEnricher"),
    "gleif_enricher": ("packages.domain.gleif_enricher", "gleif_enricher"),
    "validate_lei_checksum": ("packages.domain.gleif_enricher", "validate_lei_checksum"),
    # Email Enrichment & SMTP Engine
    "get_mx_hosts": ("packages.domain.smtp_engine", "get_mx_hosts"),
    "is_catchall_domain": ("packages.domain.smtp_engine", "is_catchall_domain"),
    "verify_email_smtp": ("packages.domain.smtp_engine", "verify_email_smtp"),
    "generate_candidate_emails": ("packages.domain.smtp_engine", "generate_candidate_emails"),
    "rank_emails": ("packages.domain.email_enricher", "rank_emails"),
    "compute_email_confidence": ("packages.domain.email_enricher", "compute_email_confidence"),
    "EmailEnrichmentEngine": ("packages.domain.email_enricher", "EmailEnrichmentEngine"),
    "email_enrichment_engine": ("packages.domain.email_enricher", "email_enrichment_engine"),
    "EmailCandidate": ("packages.domain.email_enricher", "EmailCandidate"),
    "EnrichmentResult": ("packages.domain.email_enricher", "EnrichmentResult"),
}


def __getattr__(name: str):
    if name in _SYMBOL_MAP:
        mod_path, attr = _SYMBOL_MAP[name]
        return getattr(importlib.import_module(mod_path), attr)
    return importlib.import_module(f"packages.domain.{name}")


__all__ = list(_SYMBOL_MAP.keys())

