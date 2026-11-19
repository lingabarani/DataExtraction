"""
DataExtraction — Hierarchical Service Taxonomy Engine
======================================================
Defines a structured, versioned 4-level service taxonomy:
Main Category → Subcategory → Individual Service → Descriptive Tags

Provides deterministic, rule-based classification for business attributes,
Google Maps services, and unstructured offerings.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

TAXONOMY_VERSION = "1.0.0"

# Main Category -> Subcategory -> List of (Canonical Service, [Synonyms/Keywords], [Tags])
TAXONOMY_RULES: Dict[str, Dict[str, List[Tuple[str, List[str], List[str]]]]] = {
    "Technology": {
        "Software Development": [
            ("Web Development", ["web app", "website development", "frontend", "backend", "full stack"], ["web", "software", "development"]),
            ("Mobile App Development", ["ios app", "android app", "mobile application", "flutter", "react native"], ["mobile", "app", "ios", "android"]),
            ("API & Cloud Development", ["api development", "cloud architecture", "microservices", "rest api"], ["api", "cloud", "backend"]),
        ],
        "Artificial Intelligence & Data": [
            ("Machine Learning & AI", ["machine learning", "deep learning", "generative ai", "nlp", "predictive model"], ["ai", "ml", "data"]),
            ("Data Engineering & Analytics", ["data engineering", "etl pipeline", "data warehouse", "bi analytics", "bigquery"], ["data", "analytics", "bi"]),
        ],
        "IT & Cyber Security": [
            ("Cyber Security Consulting", ["penetration testing", "soc", "infosec", "network security", "compliance"], ["security", "compliance"]),
            ("Managed IT Services", ["managed it", "helpdesk", "system administration", "it support"], ["it", "support", "managed"]),
        ],
    },
    "Professional Services": {
        "Legal Services": [
            ("Corporate & Business Law", ["corporate law", "contract", "contract review", "contract law", "incorporation", "m&a legal", "business law"], ["legal", "business", "corporate"]),
            ("Intellectual Property", ["patent filing", "trademark registration", "copyright law"], ["ip", "patent", "trademark"]),
            ("Litigation & Dispute Resolution", ["litigation", "arbitration", "commercial dispute"], ["dispute", "court", "litigation"]),
        ],
        "Accounting & Financial": [
            ("Tax Advisory & Preparation", ["tax prep", "tax return", "corporate tax", "irs audit"], ["tax", "accounting", "finance"]),
            ("Bookkeeping & Payroll", ["payroll processing", "bookkeeping", "quickbooks", "financial statements"], ["bookkeeping", "payroll"]),
            ("Financial Auditing", ["gaap audit", "financial audit", "internal audit", "assurance"], ["audit", "compliance", "cpa"]),
        ],
        "Business Consulting": [
            ("Management Consulting", ["strategy consulting", "business strategy", "operations optimization"], ["consulting", "strategy"]),
            ("Human Resources Consulting", ["hr consulting", "talent acquisition", "executive recruiting"], ["hr", "staffing", "talent"]),
        ],
    },
    "Healthcare & Medical": {
        "Primary & Urgent Care": [
            ("General Practice", ["family doctor", "primary care", "annual physical", "general consultation"], ["health", "doctor", "medical"]),
            ("Urgent Care Services", ["walk-in clinic", "urgent care", "minor emergency", "triage"], ["urgent", "clinic"]),
        ],
        "Specialized Medicine": [
            ("Dental Care", ["dentistry", "teeth cleaning", "orthodontics", "dental implant", "cavity"], ["dental", "dentist"]),
            ("Ophthalmology & Optometry", ["eye exam", "lasik", "glasses", "contact lenses", "cataract"], ["vision", "eye"]),
            ("Physical Therapy", ["physiotherapy", "rehabilitation", "sports injury", "chiropractic"], ["physio", "rehab"]),
        ],
    },
    "Construction & Trades": {
        "General Contracting": [
            ("Commercial Construction", ["commercial builder", "office renovation", "tenant improvement"], ["building", "construction"]),
            ("Residential Remodeling", ["kitchen remodel", "bathroom remodel", "home renovation"], ["remodeling", "home"]),
        ],
        "Specialty Trades": [
            ("Electrical Services", ["licensed electrician", "wiring", "panel upgrade", "ev charger install"], ["electric", "wiring"]),
            ("Plumbing Services", ["plumber", "pipe repair", "water heater", "drain cleaning"], ["plumbing", "water"]),
            ("HVAC Installation & Repair", ["hvac", "ac repair", "air conditioning", "ac installation", "heating installation", "furnace", "cooling"], ["cooling", "heating", "hvac"]),
            ("Roofing Services", ["roof repair", "shingle replacement", "commercial roofing"], ["roofing", "exterior"]),
        ],
    },
    "Marketing & Creative": {
        "Digital Marketing": [
            ("Search Engine Optimization (SEO)", ["seo audit", "link building", "local seo", "technical seo"], ["seo", "marketing", "search"]),
            ("PPC & Performance Advertising", ["google ads", "paid search", "meta ads", "performance marketing"], ["ppc", "advertising", "ads"]),
            ("Social Media Marketing", ["social media management", "influencer marketing", "content creation"], ["social", "content"]),
        ],
        "Creative & Design": [
            ("Branding & Graphic Design", ["logo design", "brand identity", "packaging design", "ui/ux design"], ["design", "branding"]),
            ("Video & Media Production", ["commercial video", "video editing", "corporate photography"], ["media", "video"]),
        ],
    },
    "Automotive & Transport": {
        "Auto Repair & Maintenance": [
            ("Mechanical Auto Repair", ["brake repair", "engine diagnostic", "transmission repair", "oil change"], ["auto", "mechanic", "car"]),
            ("Collision & Body Work", ["auto body repair", "dent removal", "paint refinishing"], ["bodywork", "collision"]),
        ],
        "Logistics & Freight": [
            ("Freight Transport", ["trucking", "freight forwarding", "cargo shipping", "less than truckload"], ["logistics", "shipping", "freight"]),
            ("Warehousing & Storage", ["pallet storage", "distribution center", "fulfillment service"], ["storage", "warehouse", "3pl"]),
        ],
    },
}


class ServiceTaxonomyClassifier:
    """Classifies unstructured attributes and service names into canonical hierarchical taxonomy."""

    def __init__(self, version: str = TAXONOMY_VERSION):
        self.version = version

    def classify_service(self, raw_name: str, group_hint: Optional[str] = None) -> Dict[str, Any]:
        """Maps an individual raw service or attribute to the taxonomy."""
        text = f"{group_hint or ''} {raw_name or ''}".lower()

        for main_cat, subcats in TAXONOMY_RULES.items():
            for subcat, services in subcats.items():
                for canonical_name, synonyms, tags in services:
                    # Direct check against canonical service name or synonyms
                    c_low = canonical_name.lower()
                    if c_low in text or any(syn in text for syn in synonyms):
                        return {
                            "main_category": main_cat,
                            "subcategory": subcat,
                            "service_name": canonical_name,
                            "tags": tags,
                            "taxonomy_version": self.version,
                            "confidence": 0.90 if c_low in text else 0.75,
                        }

        # If no taxonomy rule matches with confidence, keep uncertain services unclassified (None)
        # rather than forcing a synthetic fallback category.
        return {
            "main_category": None,
            "subcategory": None,
            "service_name": raw_name.strip()[:100] if raw_name else None,
            "tags": [],
            "taxonomy_version": self.version,
            "confidence": 0.0,
        }

    def classify_batch(self, service_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Classifies a list of service dictionaries."""
        results = []
        for item in service_items:
            name = item.get("service_name") or item.get("name") or ""
            group = item.get("group_name") or item.get("group")
            classified = self.classify_service(name, group)
            results.append({
                **item,
                "main_category": classified["main_category"],
                "subcategory": classified["subcategory"],
                "service_name": classified["service_name"] or name,
                "tags": classified["tags"],
                "taxonomy_version": classified["taxonomy_version"],
            })
        return results
