"""
Hashing and fingerprinting utilities for record provenance and deduplication.
"""

import hashlib
import json
import os
from typing import Any, Dict, Optional


def sha256_text(text: str) -> str:
    """Computes SHA-256 hash of a string."""
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def sha256_dict(data: Dict[str, Any]) -> str:
    """Computes deterministic SHA-256 hash of a dictionary."""
    serialized = json.dumps(data, sort_keys=True, default=str)
    return sha256_text(serialized)


def sha256_file(filepath: str, chunk_size: int = 65536) -> str:
    """Computes SHA-256 hash of a file by streaming chunks."""
    if not os.path.exists(filepath):
        return ""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def generate_entity_fingerprint(
    rfc: Optional[str] = None,
    normalized_name: Optional[str] = None,
    state: Optional[str] = None,
    municipality: Optional[str] = None,
    domain: Optional[str] = None,
) -> str:
    """
    Generates a deterministic entity fingerprint.
    
    If a valid RFC exists, the RFC serves as the strongest primary fingerprint.
    Otherwise, combines normalized name, state, municipality, and domain.
    """
    if rfc and len(rfc.strip()) >= 10:
        clean_rfc = rfc.strip().upper()
        return f"rfc_{clean_rfc}"

    parts = [
        (normalized_name or "").strip().lower(),
        (state or "").strip().lower(),
        (municipality or "").strip().lower(),
        (domain or "").strip().lower(),
    ]
    raw_key = "|".join(parts)
    hash_suffix = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]
    clean_name_slug = "".join(c for c in (normalized_name or "company")[:20].lower() if c.isalnum())
    return f"fp_{clean_name_slug}_{hash_suffix}"


def generate_company_id(fingerprint: str) -> str:
    """Generates a unique, reproducible company UUID-like ID from a fingerprint."""
    raw_hash = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    # Format as standard UUID 8-4-4-4-12
    return f"mx_{raw_hash[:8]}-{raw_hash[8:12]}-{raw_hash[12:16]}-{raw_hash[16:20]}-{raw_hash[20:32]}"
