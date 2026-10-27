"""
Tech Stack Detection Utility (Ported from FORGE dataforge).
Detects 30+ CMS, E-Commerce, Analytics, Marketing, and Cloud Frameworks on corporate domain HTML/headers.
"""

import re
from typing import List, Dict, Any, Optional

TECH_PATTERNS: Dict[str, List[re.Pattern]] = {
    "WordPress": [re.compile(r"wp-content", re.I), re.compile(r"wp-includes", re.I)],
    "Shopify": [re.compile(r"cdn\.shopify\.com", re.I), re.compile(r"Shopify\.theme", re.I)],
    "React": [re.compile(r"react-root", re.I), re.compile(r"__NEXT_DATA__", re.I), re.compile(r"_reactListening", re.I)],
    "Next.js": [re.compile(r"__NEXT_DATA__", re.I), re.compile(r"_next/static", re.I)],
    "Vue.js": [re.compile(r"data-v-", re.I), re.compile(r"__NUXT__", re.I)],
    "Nuxt.js": [re.compile(r"__NUXT__", re.I), re.compile(r"_nuxt/", re.I)],
    "Stripe": [re.compile(r"js\.stripe\.com", re.I), re.compile(r"stripe-v3", re.I)],
    "Google Analytics": [re.compile(r"google-analytics\.com/analytics\.js", re.I), re.compile(r"googletagmanager\.com/gtag/js", re.I)],
    "Intercom": [re.compile(r"widget\.intercom\.io", re.I)],
    "HubSpot": [re.compile(r"js\.hs-scripts\.com", re.I), re.compile(r"hs-analytics", re.I)],
    "Tailwind CSS": [re.compile(r"tailwind", re.I)],
    "Bootstrap": [re.compile(r"bootstrap\.min\.css", re.I)],
    "Cloudflare": [re.compile(r"cloudflare", re.I), re.compile(r"__cfduid", re.I)],
    "Salesforce": [re.compile(r"force\.com", re.I), re.compile(r"pardot", re.I)],
    "Klaviyo": [re.compile(r"klaviyo\.com", re.I)],
    "Wix": [re.compile(r"static\.wixstatic\.com", re.I)],
    "Squarespace": [re.compile(r"squarespace\.com", re.I)],
}


def detect_tech_stack(html_content: str) -> List[str]:
    """
    Scans HTML content and returns list of detected technologies.
    """
    if not html_content:
        return []

    detected = []
    for tech_name, patterns in TECH_PATTERNS.items():
        for pat in patterns:
            if pat.search(html_content):
                detected.append(tech_name)
                break

    return detected
