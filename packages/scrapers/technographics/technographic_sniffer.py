"""
DataExtraction — Enterprise Technographic Sniffer & Technology Stack Detector
=============================================================================
High-performance asynchronous passive and active technology detection engine.
Detects:
  1. DNS Infrastructure (MX, TXT/SPF, CNAME, A records) -> Cloud & Email Provider
  2. HTTP Response Headers (Server, X-Powered-By, Security headers)
  3. Front-end DOM & Asset Signatures (CRM, Analytics, E-commerce, Tag Managers)
"""

import asyncio
import logging
import re
import socket
from typing import Any, Dict, List, Optional, Set
import aiohttp
import dns.asyncresolver

logger = logging.getLogger("dataextraction.technographics")

# Technology Fingerprints & Signatures Catalog
CLOUD_PATTERNS = {
    "Cloudflare": [r"cloudflare", r"cf-ray", r"\.cloudflare\.com"],
    "Amazon Web Services (AWS)": [r"amazonaws\.com", r"awsdns", r"cloudfront\.net", r"elb\.amazonaws\.com", r"amazon s3"],
    "Google Cloud Platform (GCP)": [r"googlecloud", r"1e100\.net", r"googlehosted\.com", r"gcp", r"appspot\.com"],
    "Microsoft Azure": [r"azure", r"azurewebsites\.net", r"trafficmanager\.net", r"windows\.net"],
    "DigitalOcean": [r"digitalocean\.com"],
    "Vercel": [r"vercel-dns\.com", r"vercel\.app"],
}

EMAIL_PATTERNS = {
    "Google Workspace": [r"google\.com", r"googlemail\.com", r"aspmx\.l\.google\.com"],
    "Microsoft 365": [r"outlook\.com", r"mail\.protection\.outlook\.com", r"microsoft\.com"],
    "Proofpoint": [r"pphosted\.com", r"proofpoint\.com"],
    "Mimecast": [r"mimecast\.com"],
    "SendGrid": [r"sendgrid\.net"],
    "Mailgun": [r"mailgun\.org"],
}

CRM_MARKETING_PATTERNS = {
    "HubSpot": [r"js\.hs-scripts\.com", r"forms\.hubspot\.com", r"hs-analytics", r"hubspot"],
    "Salesforce": [r"salesforce\.com", r"force\.com", r"pardot\.com", r"pi\.pardot\.com"],
    "Marketo": [r"munchkin\.marketo\.net", r"marketo\.com"],
    "Klaviyo": [r"klaviyo\.com", r"static\.klaviyo\.com"],
    "ActiveCampaign": [r"activecampaign\.com", r"trackcmp\.net"],
    "Zoho CRM": [r"zoho\.com", r"zohocdn\.com"],
}

ANALYTICS_PATTERNS = {
    "Google Analytics 4": [r"gtag/js\?id=G-", r"google-analytics\.com/analytics\.js"],
    "Google Tag Manager": [r"googletagmanager\.com/gtm\.js"],
    "Segment": [r"cdn\.segment\.com/analytics\.js"],
    "Mixpanel": [r"cdn\.mxpnl\.com"],
    "Hotjar": [r"static\.hotjar\.com"],
}

ECOMMERCE_CMS_PATTERNS = {
    "Shopify": [r"cdn\.shopify\.com", r"myshopify\.com"],
    "WordPress": [r"wp-content", r"wp-includes"],
    "WooCommerce": [r"woocommerce"],
    "Magento": [r"skin/frontend", r"static/version.*frontend"],
    "Next.js": [r"/_next/static", r"__NEXT_DATA__"],
    "Webflow": [r"assets\.website-files\.com", r"webflow\.js"],
}


class TechnographicSniffer:
    """Enterprise Technographic Stack Detector across DNS, HTTP headers, and DOM scripts."""

    def __init__(self, timeout_seconds: float = 8.0):
        self.timeout = timeout_seconds
        self.resolver = dns.asyncresolver.Resolver()
        self.resolver.lifetime = timeout_seconds
        self.resolver.nameservers = ["8.8.8.8", "1.1.1.1"]

    async def sniff_domain(self, domain: str) -> Dict[str, Any]:
        """Perform comprehensive technographic audit for a corporate apex domain."""
        clean_domain = domain.strip().lower()
        if clean_domain.startswith("http://") or clean_domain.startswith("https://"):
            clean_domain = re.sub(r"^https?://(www\.)?", "", clean_domain).split("/")[0]

        detected_technologies: List[Dict[str, Any]] = []
        tech_categories: Set[str] = set()
        primary_cloud: Optional[str] = None
        primary_crm: Optional[str] = None
        primary_email_provider: Optional[str] = None

        # 1. DNS Reconnaissance (MX, TXT/SPF, CNAME, A)
        dns_results = await self._probe_dns(clean_domain)
        for tech in dns_results.get("technologies", []):
            detected_technologies.append(tech)
            tech_categories.add(tech["category"])
            if tech["category"] == "Cloud Infrastructure" and not primary_cloud:
                primary_cloud = tech["name"]
            if tech["category"] == "Email Service Provider" and not primary_email_provider:
                primary_email_provider = tech["name"]

        # 2. HTTP Probing (Headers & HTML Script Signatures)
        http_results = await self._probe_http(clean_domain)
        for tech in http_results.get("technologies", []):
            if not any(t["name"] == tech["name"] for t in detected_technologies):
                detected_technologies.append(tech)
                tech_categories.add(tech["category"])
                if tech["category"] == "Cloud Infrastructure" and not primary_cloud:
                    primary_cloud = tech["name"]
                if tech["category"] == "CRM" and not primary_crm:
                    primary_crm = tech["name"]

        return {
            "domain": clean_domain,
            "primary_cloud": primary_cloud or "On-Premises / Other",
            "primary_crm": primary_crm or "None Detected",
            "primary_email_provider": primary_email_provider or "Standard SMTP",
            "tech_categories": sorted(list(tech_categories)),
            "detected_technologies": detected_technologies,
            "dns_telemetry": dns_results.get("records", {}),
            "http_status": http_results.get("status_code"),
        }

    async def _probe_dns(self, domain: str) -> Dict[str, Any]:
        technologies = []
        records = {"mx": [], "txt": [], "cname": [], "a": []}

        # MX Records (Email Provider)
        try:
            mx_answers = await self.resolver.resolve(domain, "MX")
            for rdata in mx_answers:
                mx_str = str(rdata.exchange).lower()
                records["mx"].append(mx_str)
                for provider, patterns in EMAIL_PATTERNS.items():
                    if any(re.search(pat, mx_str) for pat in patterns):
                        if not any(t["name"] == provider for t in technologies):
                            technologies.append({
                                "name": provider,
                                "category": "Email Service Provider",
                                "confidence": 1.0,
                                "detected_via": "DNS_MX",
                            })
        except Exception:
            pass

        # TXT / SPF Records (Verification & Delivery Platforms)
        try:
            txt_answers = await self.resolver.resolve(domain, "TXT")
            for rdata in txt_answers:
                txt_str = "".join([s.decode("utf-8", errors="ignore") for s in rdata.strings]).lower()
                records["txt"].append(txt_str[:120])
                for provider, patterns in EMAIL_PATTERNS.items():
                    if any(re.search(pat, txt_str) for pat in patterns):
                        if not any(t["name"] == provider for t in technologies):
                            technologies.append({
                                "name": provider,
                                "category": "Email Service Provider",
                                "confidence": 0.95,
                                "detected_via": "DNS_TXT",
                            })
                for crm, patterns in CRM_MARKETING_PATTERNS.items():
                    if any(re.search(pat, txt_str) for pat in patterns):
                        if not any(t["name"] == crm for t in technologies):
                            technologies.append({
                                "name": crm,
                                "category": "CRM",
                                "confidence": 0.90,
                                "detected_via": "DNS_TXT",
                            })
        except Exception:
            pass

        # CNAME Records (CDN / Hosting)
        try:
            cname_answers = await self.resolver.resolve(domain, "CNAME")
            for rdata in cname_answers:
                cname_str = str(rdata.target).lower()
                records["cname"].append(cname_str)
                for cloud, patterns in CLOUD_PATTERNS.items():
                    if any(re.search(pat, cname_str) for pat in patterns):
                        if not any(t["name"] == cloud for t in technologies):
                            technologies.append({
                                "name": cloud,
                                "category": "Cloud Infrastructure",
                                "confidence": 0.95,
                                "detected_via": "DNS_CNAME",
                            })
        except Exception:
            pass

        return {"technologies": technologies, "records": records}

    async def _probe_http(self, domain: str) -> Dict[str, Any]:
        technologies = []
        status_code = None
        headers_dict = {}

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        url = f"https://{domain}"
        timeout = aiohttp.ClientTimeout(total=self.timeout)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers, ssl=False, allow_redirects=True) as resp:
                    status_code = resp.status
                    headers_dict = dict(resp.headers)
                    headers_text = " ".join([f"{k}:{v}" for k, v in resp.headers.items()]).lower()

                    # 1. Inspect HTTP Headers for Cloud / CDN / Server
                    for cloud, patterns in CLOUD_PATTERNS.items():
                        if any(re.search(pat, headers_text) for pat in patterns):
                            technologies.append({
                                "name": cloud,
                                "category": "Cloud Infrastructure",
                                "confidence": 0.95,
                                "detected_via": "HTTP_HEADER",
                            })

                    # Read first 150KB of HTML for script signatures
                    html = await resp.text(errors="ignore")
                    html_snippet = html[:150000].lower()

                    # 2. Inspect CRM & Marketing
                    for crm, patterns in CRM_MARKETING_PATTERNS.items():
                        if any(re.search(pat, html_snippet) for pat in patterns):
                            technologies.append({
                                "name": crm,
                                "category": "CRM",
                                "confidence": 0.95,
                                "detected_via": "DOM_SCRIPT",
                            })

                    # 3. Inspect Analytics
                    for analytics, patterns in ANALYTICS_PATTERNS.items():
                        if any(re.search(pat, html_snippet) for pat in patterns):
                            technologies.append({
                                "name": analytics,
                                "category": "Analytics",
                                "confidence": 0.90,
                                "detected_via": "DOM_SCRIPT",
                            })

                    # 4. Inspect CMS & E-Commerce
                    for cms, patterns in ECOMMERCE_CMS_PATTERNS.items():
                        if any(re.search(pat, html_snippet) for pat in patterns):
                            technologies.append({
                                "name": cms,
                                "category": "E-Commerce & CMS",
                                "confidence": 0.95,
                                "detected_via": "DOM_ASSET",
                            })
        except Exception:
            pass

        return {
            "status_code": status_code,
            "technologies": technologies,
            "headers": {k: v for k, v in headers_dict.items() if k.lower() in ("server", "cf-ray", "x-powered-by")},
        }


technographic_sniffer = TechnographicSniffer()
