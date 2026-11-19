"""Name sanity checks shared by sources that extract people from semi-structured text."""

from __future__ import annotations

import re
from typing import Iterable

from packages.leadintel.deduplication import normalize_string

_COMPANY_WORDS = re.compile(
    r"\b(llc|inc|corp|corporation|company|co|ltd|lp|llp|pllc|trust|foundation|association|services|service|agency|"
    r"care|health|healthcare|home|homes|center|centre|group|holdings|partners|system|systems|team|staff|about|contact|"
    r"our|meet|us|the|and|of|for|home|senior|living|nursing|hospice|clinic|office|careers|leadership|management)\b",
    re.I,
)
_NAME_TOKEN = re.compile(r"^[A-Z][a-zA-Z'\-\.]{0,24}$")


def looks_like_person(name: str, org_names: Iterable[str] = ()) -> bool:
    """True for 2-5 capitalised word names that are not company phrases or the organization's own name."""
    n = (name or "").strip()
    words = n.replace(",", " ").split()
    if not 2 <= len(words) <= 5:
        return False
    if _COMPANY_WORDS.search(n):
        return False
    core = [w for w in words if w.rstrip(".").lower() not in {"dr", "mr", "mrs", "ms", "rn", "lpn", "md", "jr", "sr", "ii", "iii"}]
    if len(core) < 2 or not all(_NAME_TOKEN.match(w) for w in core):
        return False
    return normalize_string(n) not in {normalize_string(o) for o in org_names if o}


_HONORIFICS = {"dr", "mr", "mrs", "ms", "miss", "prof", "rev"}
_CREDENTIALS = {"rn", "lpn", "lvn", "cna", "md", "do", "np", "pa", "pa-c", "dnp", "phd", "msw", "lcsw", "mba", "jr", "sr",
                "ii", "iii", "iv", "esq", "bsn", "msn", "rn-bc", "cmc", "nha", "lnha"}


def canonical_person_name(name: str) -> str:
    """Lowercase name without honorifics, credentials or punctuation, for matching ("Wendy Edison, RN" == "Wendy Edison")."""
    parts = re.sub(r"[^\w\s\-]", " ", (name or "").lower()).split()
    parts = [p for p in parts if p not in _HONORIFICS and p not in _CREDENTIALS]
    return " ".join(parts)