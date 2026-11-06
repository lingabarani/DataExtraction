"""
DataExtraction — Pipeline Package (Legacy Compatibility Shim)
=============================================================
This package is maintained for backward compatibility. The canonical enterprise domain
services now reside in `packages.domain`.
"""

import sys
import warnings

def __getattr__(name: str):
    import packages.domain as _domain
    if hasattr(_domain, name):
        warnings.warn(
            f"Importing {name} from packages.pipeline is deprecated. Import from packages.domain instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(_domain, name)
    raise AttributeError(f"module 'packages.pipeline' has no attribute '{name}'")


__all__ = [
    "clean_legal_suffixes",
    "clean_domain",
    "normalize_company",
    "normalize_person",
    "validate_email",
    "validate_phone",
    "validate_contact",
    "validate_ein",
    "validate_rfc",
    "validate_tax_id",
    "normalize_postal_code",
    "validate_coordinates",
    "Deduplicator",
    "DedupResult",
    "SplinkIdentityLinker",
    "SplinkEngine",
    "build_us_lead",
    "build_mexico_lead",
    "GLEIFEnricher",
    "gleif_enricher",
]
