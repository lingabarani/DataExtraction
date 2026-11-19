"""
DataExtraction — Website Technology Stack Discovery
===================================================
Passive technology detection analyzing HTTP response headers, meta tags,
script sources, and link patterns across crawled HTML pages.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("dataextraction.enrichment.tech_stack")

# Technology Signatures: Category -> Tech Name -> List of (match_target, regex_pattern, version_extractor_regex)
# match_target: 'header' | 'html' | 'script' | 'meta'
TECH_SIGNATURES: Dict[str, Dict[str, List[Tuple[str, str, Optional[str]]]]] = {
    "CMS": {
        "WordPress": [
            ("html", r"wp-content/|wp-includes/|<meta name=[\"']generator[\"'] content=[\"']WordPress", r"WordPress\s*([0-9.]+)"),
            ("header", r"x-powered-by:.*wordpress", None),
        ],
        "Shopify": [
            ("html", r"cdn\.shopify\.com|Shopify\.theme|<meta id=[\"']shopify-", None),
            ("header", r"x-shopid|x-shardid", None),
        ],
        "Wix": [
            ("html", r"static\.wixstatic\.com|_wixCatalogData", None),
            ("header", r"x-wix-request-id", None),
        ],
        "Squarespace": [
            ("html", r"static1\.squarespace\.com|Squarespace\.Constants", None),
        ],
        "Webflow": [
            ("html", r"data-wf-page|data-wf-site|assets\.website-files\.com", None),
        ],
        "HubSpot CMS": [
            ("html", r"hs-scripts\.com|hbspt\.forms", None),
        ],
    },
    "Framework": {
        "Next.js": [
            ("html", r"/_next/static/|__NEXT_DATA__", None),
            ("header", r"x-powered-by:.*next\.js", None),
        ],
        "React": [
            ("html", r"data-reactroot|react-dom", None),
        ],
        "Vue.js": [
            ("html", r"data-v-[a-f0-9]{6,8}|v-bind|v-model", None),
        ],
        "Angular": [
            ("html", r"ng-version=[\"']([0-9.]+)[\"']|ng-app=", r"ng-version=[\"']([0-9.]+)[\"']"),
        ],
        "Tailwind CSS": [
            ("html", r"tailwind|font-sans|max-w-7xl|mx-auto", None),
        ],
    },
    "Analytics": {
        "Google Analytics": [
            ("html", r"googletagmanager\.com/gtag/js|ga\('create'|UA-[0-9]+-[0-9]+|G-[A-Z0-9]+", r"(G-[A-Z0-9]+|UA-[0-9]+-[0-9]+)"),
        ],
        "Google Tag Manager": [
            ("html", r"googletagmanager\.com/gtm\.js|GTM-[A-Z0-9]+", r"(GTM-[A-Z0-9]+)"),
        ],
        "Segment": [
            ("html", r"cdn\.segment\.com/analytics\.js|analytics\.load\([\"']", None),
        ],
        "Hotjar": [
            ("html", r"static\.hotjar\.com/c/hotjar-([0-9]+)\.js", None),
        ],
        "Mixpanel": [
            ("html", r"cdn\.mxpnl\.com/libs/mixpanel|mixpanel\.init", None),
        ],
    },
    "CRM & Marketing": {
        "HubSpot": [
            ("html", r"js\.hs-scripts\.com|js\.hsforms\.net", None),
        ],
        "Marketo": [
            ("html", r"munchkin\.marketo\.net|marketo\.com/js", None),
        ],
        "Intercom": [
            ("html", r"widget\.intercom\.io|intercomSettings", None),
        ],
        "Zendesk": [
            ("html", r"static\.zdassets\.com/ekr/snippet\.js|zE\(", None),
        ],
        "Drift": [
            ("html", r"js\.driftt\.com/include/|drift\.load\(", None),
        ],
    },
    "Hosting & CDN": {
        "Cloudflare": [
            ("header", r"cf-ray:|cf-cache-status:|server:\s*cloudflare", None),
            ("html", r"cdnjs\.cloudflare\.com", None),
        ],
        "Vercel": [
            ("header", r"x-vercel-id:|server:\s*vercel", None),
        ],
        "AWS CloudFront": [
            ("header", r"x-amz-cf-id:|via:.*cloudfront", None),
        ],
        "Fastly": [
            ("header", r"x-fastly-request-id:|fastly-debug", None),
        ],
    },
    "E-commerce": {
        "Stripe": [
            ("html", r"js\.stripe\.com/v[23]/", None),
        ],
        "WooCommerce": [
            ("html", r"woocommerce|wc-add-to-cart", None),
        ],
        "Magento": [
            ("html", r"/skin/frontend/|Mage\.Cookies", None),
        ],
    },
}


class TechStackDetector:
    """Detects technologies from HTML content and response headers."""

    @staticmethod
    def detect(html_pages: Dict[str, str], headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """
        Analyzes crawled pages and HTTP headers.
        Returns deduplicated list of detected technologies.
        """
        detected: Dict[str, Dict[str, Any]] = {}
        header_str = "\n".join(f"{k.lower()}: {v.lower()}" for k, v in (headers or {}).items())

        for url, html in html_pages.items():
            if not html:
                continue

            for category, tech_dict in TECH_SIGNATURES.items():
                for tech_name, rules in tech_dict.items():
                    if tech_name in detected:
                        continue

                    for target, pattern, version_pat in rules:
                        matched = False
                        version = None

                        if target == "header" and header_str:
                            m = re.search(pattern, header_str, re.IGNORECASE)
                            if m:
                                matched = True
                                if version_pat:
                                    v_m = re.search(version_pat, header_str, re.IGNORECASE)
                                    version = v_m.group(1) if v_m else None
                        elif target in ("html", "script", "meta"):
                            m = re.search(pattern, html, re.IGNORECASE)
                            if m:
                                matched = True
                                if version_pat:
                                    v_m = re.search(version_pat, html, re.IGNORECASE)
                                    version = v_m.group(1) if v_m else None

                        if matched:
                            detected[tech_name] = {
                                "technology_name": tech_name,
                                "category": category,
                                "version": version,
                                "evidence_url": url,
                                "confidence": 0.90 if target == "header" else 0.80,
                            }
                            break

        return list(detected.values())
