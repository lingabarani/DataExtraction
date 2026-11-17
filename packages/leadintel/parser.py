"""
HTML parser for team members, leadership, and contact points on corporate websites.
Extracts individual executive names, titles, emails, and phone numbers from unstructured pages.
"""

import logging
import re
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup

from .phone_finder import PhoneFinder

logger = logging.getLogger("dataextraction.leadintel.parser")

TITLE_KEYWORDS = [
    "owner", "founder", "co-founder", "ceo", "chief executive", "president",
    "administrator", "director", "director of nursing", "don", "executive director",
    "manager", "supervisor", "coordinator", "nurse", "physician", "officer",
    "vice president", "vp", "partner", "principal", "managing director",
]

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")


class TeamPageParser:
    """Extracts team member records from HTML blocks."""

    def __init__(self):
        self.phone_finder = PhoneFinder()

    def parse_team_members(self, html: str, source_url: Optional[str] = None) -> List[Dict[str, Any]]:
        """Parse structured leadership / team members from about/team HTML."""
        if not html or not html.strip():
            return []

        soup = BeautifulSoup(html, "lxml")
        members: List[Dict[str, Any]] = []

        # Remove script and style tags
        for el in soup(["script", "style", "noscript", "svg"]):
            el.decompose()

        # Strategy 1: Look for dedicated member containers
        container_re = re.compile(r"(member|staff|leader|person|bio|profile|team-card|team-item)", re.I)
        containers = soup.find_all(
            ["div", "article", "section", "li"],
            class_=container_re,
        )
        if not containers:
            # Fallback to broader match
            containers = soup.find_all(
                ["div", "article", "section", "li"],
                class_=re.compile(r"(team|staff|leader)", re.I),
            )

        seen_names = set()

        for c in containers:
            # Skip parent containers that contain nested member cards
            if c.find(["div", "article", "section", "li"], class_=container_re):
                continue

            text = c.get_text(separator=" ", strip=True)
            # Find candidate name and title
            headings = c.find_all(["h2", "h3", "h4", "h5", "strong"])
            if not headings:
                continue

            name_candidate = headings[0].get_text(strip=True)
            # Filter unrealistic names
            if len(name_candidate) < 3 or len(name_candidate) > 50 or any(char in name_candidate for char in "@{}[]<>"):
                continue
            if name_candidate.lower() in seen_names:
                continue

            # Look for title in second heading or paragraph
            title_candidate = None
            if len(headings) > 1:
                title_candidate = headings[1].get_text(strip=True)
            if not title_candidate:
                paras = c.find_all("p")
                for p in paras:
                    p_text = p.get_text(strip=True)
                    if any(t in p_text.lower() for t in TITLE_KEYWORDS) and len(p_text) < 100:
                        title_candidate = p_text
                        break

            # Find emails
            emails = EMAIL_REGEX.findall(text)
            # Find phones
            phones = self.phone_finder.extract_from_text(text, source_url=source_url)

            # Determine role type
            role_type = "executive"
            if title_candidate:
                low = title_candidate.lower()
                if "owner" in low or "founder" in low:
                    role_type = "owner"
                elif "administrator" in low:
                    role_type = "administrator"
                elif "nursing" in low or "don" in low:
                    role_type = "director_of_nursing"

            if name_candidate and (title_candidate or emails or phones):
                seen_names.add(name_candidate.lower())
                members.append({
                    "full_name": name_candidate,
                    "title": title_candidate,
                    "role_type": role_type,
                    "emails": list(dict.fromkeys(emails)),
                    "phones": [p["e164"] for p in phones if p.get("e164")],
                    "source_url": source_url,
                })

        return members
