"""
DataExtraction — C-Suite & Executive Leadership Extractor
=========================================================
Extracts C-suite executives, founders, and senior leadership from crawled corporate pages
(/about, /team, /leadership, /board, /management).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("dataextraction.enrichment.csuite_extractor")

# Strict C-suite and executive role patterns
_EXECUTIVE_TITLES = [
    (r"\bchief\s+executive\s+officer\b|\bceo\b", "Chief Executive Officer"),
    (r"\bchief\s+technology\s+officer\b|\bcto\b", "Chief Technology Officer"),
    (r"\bchief\s+operating\s+officer\b|\bcoo\b", "Chief Operating Officer"),
    (r"\bchief\s+financial\s+officer\b|\bcfo\b", "Chief Financial Officer"),
    (r"\bchief\s+marketing\s+officer\b|\bcmo\b", "Chief Marketing Officer"),
    (r"\bchief\s+information\s+officer\b|\bcio\b", "Chief Information Officer"),
    (r"\bchief\s+revenue\s+officer\b|\bcro\b", "Chief Revenue Officer"),
    (r"\bchief\s+product\s+officer\b|\bcpo\b", "Chief Product Officer"),
    (r"\bpresident\b", "President"),
    (r"\bco-?founder\b", "Co-Founder"),
    (r"\bfounder\b", "Founder"),
    (r"\bmanaging\s+director\b", "Managing Director"),
    (r"\bgeneral\s+counsel\b", "General Counsel"),
    (r"\bvice\s+president\b|\bvp\b", "Vice President"),
    (r"\bpartner\b", "Partner"),
    (r"\bboard\s+member\b|\bdirector\b", "Director"),
]

_NAME_PATTERN = re.compile(
    r"\b([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"
)

_JUNK_NAMES = {
    "About Us", "Contact Us", "Our Team", "Leadership Team", "Board Members",
    "Privacy Policy", "Terms Service", "Learn More", "Read More", "Get Started",
    "All Rights", "United States", "North America", "San Francisco", "New York",
    "Executive Officer", "Technology Officer", "Operating Officer", "Financial Officer",
}


class CSuiteExtractor:
    def __init__(self, suppressed_fn: Optional[Callable[[Optional[str]], bool]] = None):
        self._suppressed = suppressed_fn or (lambda _v: False)

    def extract_leadership(
        self,
        html_pages: Dict[str, str],
        place_id: Optional[str] = None,
        company_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Extracts executive leadership from HTML pages."""
        candidates: List[Dict[str, Any]] = []
        seen = set()

        for url, html in html_pages.items():
            if not html:
                continue

            # Prioritize team/about/leadership pages
            url_low = url.lower()
            is_team_page = any(k in url_low for k in ("about", "team", "leader", "people", "management", "exec"))

            # Simple clean text
            clean_text = re.sub(r"<script[^>]*>[\s\S]*?</script>|<style[^>]*>[\s\S]*?</style>", " ", html, flags=re.I)
            text = re.sub(r"<[^>]+>", "\n", clean_text)
            lines = [line.strip() for line in text.split("\n") if line.strip()]

            for i, line in enumerate(lines):
                for pat, canonical_title in _EXECUTIVE_TITLES:
                    if re.search(pat, line, re.I):
                        # The executive name is typically on the same line, the line right before, or right after
                        search_lines = []
                        if i > 0:
                            search_lines.append(lines[i - 1])
                        search_lines.append(line)
                        if i < len(lines) - 1:
                            search_lines.append(lines[i + 1])

                        for s_line in search_lines:
                            for m in _NAME_PATTERN.finditer(s_line):
                                name = m.group(1).strip()
                                if name in _JUNK_NAMES or len(name.split()) < 2:
                                    continue
                                if self._suppressed(name):
                                    continue

                                key = (name.lower(), canonical_title.lower())
                                if key in seen:
                                    continue
                                seen.add(key)

                                candidates.append({
                                    "place_id": place_id or "unknown",
                                    "company_id": company_id,
                                    "full_name": name,
                                    "role_title": canonical_title,
                                    "source_url": url,
                                    "extraction_method": "regex_csuite",
                                    "confidence": 0.90 if is_team_page else 0.75,
                                    "run_id": run_id,
                                })
                                break

        return candidates
