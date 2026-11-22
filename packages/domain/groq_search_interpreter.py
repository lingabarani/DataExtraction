"""
DataExtraction — Groq-Powered Semantic Query Expansion & Natural-Language Search Interpreter
=============================================================================================
Translates natural-language search queries into strictly validated, structured JSON filter plans
grounded in the existing schema of PostgreSQL 18.6 (master_dataextraction) and OpenSearch 2.x.

Features:
  1. Multi-Key Resilient Rotation: Primary (GROQ_API_KEY) and secondary (GROQ_API_KEYS).
  2. Multi-Tier Failover: Groq API -> Local Ollama (llama3.1:8b) -> Deterministic Regex Heuristics.
  3. Strict Pydantic v2 Validation: ParsedSearchPlan schema with zero raw SQL execution.
  4. Live Schema Grounding: Knows exact column names of organizations, persons, locations, and contact_emails.
  5. Niche Vertical Expansion: Expands verticals (e.g. homecare, SaaS, logistics) into 8-12 synonyms and NAICS codes.
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

from packages.infrastructure.config_manager import config_manager
from packages.infrastructure.ollama_client import ollama_client

logger = logging.getLogger("dataextraction.domain.groq_search_interpreter")

# ── Reference Dictionaries for Heuristic Normalization & Fallback ──────────

US_STATE_MAP: Dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY",
}

SENIORITY_KEYWORDS: Dict[str, str] = {
    "c-suite": "C_SUITE", "csuite": "C_SUITE", "c suite": "C_SUITE", "chief": "C_SUITE",
    "ceo": "C_SUITE", "cto": "C_SUITE", "cfo": "C_SUITE", "coo": "C_SUITE", "cmo": "C_SUITE", "cro": "C_SUITE",
    "vp": "VP", "vps": "VP", "vice president": "VP", "vice presidents": "VP",
    "director": "DIRECTOR", "directors": "DIRECTOR", "head of": "DIRECTOR",
    "manager": "MANAGER", "managers": "MANAGER", "lead": "MANAGER",
    "founder": "FOUNDER", "founders": "FOUNDER", "owner": "FOUNDER", "co-founder": "FOUNDER",
    "senior": "SENIOR", "principal": "SENIOR", "staff": "SENIOR",
}

DEPARTMENT_KEYWORDS: Dict[str, str] = {
    "engineering": "ENGINEERING_TECH", "developer": "ENGINEERING_TECH", "software": "ENGINEERING_TECH",
    "tech": "ENGINEERING_TECH", "technology": "ENGINEERING_TECH", "it": "ENGINEERING_TECH",
    "sales": "SALES", "business development": "SALES", "bdr": "SALES", "sdr": "SALES", "account executive": "SALES",
    "marketing": "MARKETING", "growth": "MARKETING", "brand": "MARKETING", "demand": "MARKETING",
    "operations": "OPERATIONS", "ops": "OPERATIONS",
    "finance": "FINANCE", "accounting": "FINANCE",
    "hr": "HUMAN_RESOURCES", "human resources": "HUMAN_RESOURCES", "recruiting": "HUMAN_RESOURCES", "talent": "HUMAN_RESOURCES",
    "legal": "LEGAL", "compliance": "LEGAL",
}

COMMON_TECH_STACKS: List[str] = [
    "salesforce", "hubspot", "aws", "amazon web services", "google cloud", "gcp",
    "azure", "microsoft azure", "react", "next.js", "angular", "vue", "python",
    "postgresql", "snowflake", "databricks", "stripe", "shopify", "wordpress",
    "workday", "zendesk", "marketo", "docker", "kubernetes",
]

COMMON_NAICS_VERTICALS: Dict[str, List[str]] = {
    "homecare": ["621610", "624120", "623312", "623110", "624190"],
    "home care": ["621610", "624120", "623312", "623110", "624190"],
    "eldercare": ["624120", "623312", "623110", "621610"],
    "healthcare": ["621111", "621112", "621210", "621310", "621610", "622110"],
    "software": ["511210", "518210", "541511", "541512"],
    "saas": ["511210", "518210", "541511"],
    "logistics": ["484110", "484121", "488510", "493110"],
    "manufacturing": ["332710", "334418", "333999", "311999"],
    "finance": ["522110", "522291", "523920", "523930"],
}


# ── Pydantic Schema: ParsedSearchPlan ──────────────────────────────────────

class ParsedSearchPlan(BaseModel):
    mode: Literal["company", "people"] = Field(
        default="company", description="Target search mode: company or people"
    )
    expanded_keywords: List[str] = Field(
        default_factory=list,
        description="8-12 high-signal synonyms, industry terms, and sub-vertical phrases"
    )
    naics_codes: List[str] = Field(
        default_factory=list,
        description="Relevant 4-to-6 digit NAICS codes matching the target vertical"
    )
    states: List[str] = Field(
        default_factory=list,
        description="Extracted 2-letter uppercase US state codes (e.g. ['TX', 'CA'])"
    )
    cities: List[str] = Field(
        default_factory=list,
        description="Target city names (e.g. ['Dallas', 'Austin'])"
    )
    countries: List[str] = Field(
        default_factory=lambda: ["US"],
        description="Target country codes (e.g. ['US', 'MX'])"
    )
    target_titles: List[str] = Field(
        default_factory=list,
        description="Target job titles (e.g. ['Chief Medical Officer', 'VP of Sales'])"
    )
    seniority_tiers: List[str] = Field(
        default_factory=list,
        description="Standardized tiers: C_SUITE, VP, DIRECTOR, MANAGER, FOUNDER, SENIOR"
    )
    departments: List[str] = Field(
        default_factory=list,
        description="Normalized departments: ENGINEERING_TECH, SALES, MARKETING, OPERATIONS, FINANCE, HUMAN_RESOURCES, LEGAL"
    )
    technologies: List[str] = Field(
        default_factory=list,
        description="Identified tech stack or CRM requirements (e.g. ['Salesforce', 'AWS'])"
    )
    require_verified_email: bool = Field(
        default=False,
        description="True if verified email or deliverable contact is required"
    )
    require_direct_phone: bool = Field(
        default=False,
        description="True if direct dials or phone numbers are explicitly requested"
    )
    min_headcount: Optional[int] = Field(default=None)
    max_headcount: Optional[int] = Field(default=None)
    assistant_summary: str = Field(
        ...,
        description="Concise, professional 1-sentence summary of the search criteria"
    )
    source_model: str = Field(
        default="groq-openai-gpt-oss-20b",
        description="Underlying engine or model that produced this plan"
    )


# ── System Instruction Grounded in Master DataExtraction Schema ────────────

SYSTEM_PROMPT = """You are a Principal B2B Search Query Planner & Semantic Expander for the DataExtraction intelligence platform.
Your task is to translate natural language user questions into a strictly validated JSON search plan that will be compiled into parameterized SQL queries against our database.

EXISTING DATABASE SCHEMA COLUMNS:
1. master_dataextraction.organizations:
   - legal_name, display_name, primary_domain
   - industry, sub_industry, primary_industry_naics, primary_industry_sic
   - employee_count_min, employee_count_max, annual_revenue_usd, latest_funding_stage
   - technologies (jsonb), tech_categories (ARRAY), primary_crm, primary_cloud
   - intent_score, intent_strength, intent_topics (ARRAY), trust_score
   - short_description
2. master_dataextraction.persons:
   - full_name, current_primary_title, seniority_level (C_SUITE, VP, DIRECTOR, MANAGER, FOUNDER, SENIOR)
   - department (ENGINEERING_TECH, SALES, MARKETING, OPERATIONS, FINANCE, HUMAN_RESOURCES, LEGAL)
   - primary_email, primary_phone_e164, email_status ('VERIFIED'), propensity_to_buy_score
   - city, state, state_code, country
3. master_dataextraction.locations:
   - city, state, state_code, country, postal_code

RULES:
1. ALWAYS output a single STRICT valid JSON object with the exact keys:
   - "mode": "company" or "people"
   - "expanded_keywords": list of 8 to 12 high-signal synonyms, industry terms, sub-verticals, and Spanish/English variants.
     Example for "home care": ["home health care", "senior care", "elderly assistance", "skilled nursing", "in-home hospice", "assisted living", "personal care aide", "caregiving services", "home care services", "elder care", "senior living", "adult day care"]
   - "naics_codes": list of 4-to-6 digit NAICS industry codes (e.g. ["621610", "624120", "623312", "623110"])
   - "states": list of 2-letter uppercase US state codes (e.g. ["TX", "CA"])
   - "cities": list of city names
   - "countries": list of country codes (e.g. ["US"])
   - "target_titles": list of job titles (for people mode, e.g. ["CEO", "Director of Sales"])
   - "seniority_tiers": list from ["C_SUITE", "VP", "DIRECTOR", "MANAGER", "FOUNDER", "SENIOR"]
   - "departments": list from ["ENGINEERING_TECH", "SALES", "MARKETING", "OPERATIONS", "FINANCE", "HUMAN_RESOURCES", "LEGAL"]
   - "technologies": list of tech stack names ONLY IF EXPLICITLY MENTIONED BY THE USER in their query (e.g. "using Salesforce", "on AWS"). If the user did not explicitly mention a technology, ALWAYS return an empty list []! Never hallucinate or assume tech stacks.
   - "require_verified_email": boolean (true ONLY if user explicitly asks for emails, verified contacts, or deliverable emails)
   - "require_direct_phone": boolean (true ONLY if user explicitly asks for phone numbers or direct dials)
   - "min_headcount": integer or null
   - "max_headcount": integer or null
   - "assistant_summary": a 1-sentence concise description explaining the search plan to the user.

2. Do not write raw SQL queries, markdown codeblocks or preamble. Output the JSON object directly.
"""


# ── Groq Search Interpreter Service ────────────────────────────────────────

class GroqSearchInterpreter:
    """
    Async service for semantic query expansion using Groq API with multi-key rotation,
    local Ollama fallback, and deterministic heuristic fallback.
    """

    def __init__(self):
        # Resolve keys from environment or config_manager
        k1 = config_manager.get("GROQ_API_KEY", "").strip() or os.getenv("GROQ_API_KEY", "").strip()
        k2 = config_manager.get("GROQ_API_KEYS", "").strip() or os.getenv("GROQ_API_KEYS", "").strip()

        self.api_keys: List[str] = [k for k in [k1, k2] if k]
        self.base_url = "https://api.groq.com/openai/v1"

        # Model hierarchy: gpt-oss-20b is verified fast & operational on this Groq account
        self.default_model = config_manager.get("GROQ_MODEL", "openai/gpt-oss-20b").strip()
        self.fallback_model = config_manager.get("GROQ_FALLBACK_MODEL", "openai/gpt-oss-120b").strip()

        logger.info(
            "GroqSearchInterpreter initialized with %d API key(s), primary model=%s, fallback=%s",
            len(self.api_keys),
            self.default_model,
            self.fallback_model,
        )

    def _get_openai_client(self, api_key: str):
        """Constructs an OpenAI SDK client pointed at Groq API endpoint."""
        from openai import OpenAI
        return OpenAI(base_url=self.base_url, api_key=api_key, timeout=5.0)

    async def interpret_query(
        self,
        query: str,
        mode: str = "company",
    ) -> ParsedSearchPlan:
        """
        Translates a natural language query into a ParsedSearchPlan.
        Attempts Groq Key 1 -> Groq Key 2 -> Ollama -> Regex Heuristics.
        """
        clean_query = (query or "").strip()
        if not clean_query:
            return ParsedSearchPlan(
                mode="company" if mode not in ("company", "people") else mode,
                expanded_keywords=[],
                assistant_summary="Please enter a natural language prompt to begin searching.",
                source_model="empty-input",
            )

        # ── Tier 1 & 2: Groq OpenAI-Compatible API with Key Rotation ─────────
        for idx, key in enumerate(self.api_keys):
            for model_name in [self.default_model, self.fallback_model]:
                try:
                    logger.debug(
                        "Attempting Groq semantic query expansion with key #%d, model=%s",
                        idx + 1,
                        model_name,
                    )
                    client = self._get_openai_client(key)

                    prompt_content = (
                        f"Target Mode: {mode}\n"
                        f"User Query: {clean_query}\n"
                        f"Return a strict JSON response."
                    )

                    # Execute in worker thread to keep FastAPI loop fully asynchronous
                    loop = asyncio.get_running_loop()
                    resp = await loop.run_in_executor(
                        None,
                        lambda: client.chat.completions.create(
                            model=model_name,
                            messages=[
                                {"role": "system", "content": SYSTEM_PROMPT},
                                {"role": "user", "content": prompt_content},
                            ],
                            response_format={"type": "json_object"},
                            temperature=0.1,
                            max_tokens=1200,
                        ),
                    )

                    raw_content = resp.choices[0].message.content
                    if raw_content:
                        data = json.loads(raw_content)
                        # Sanitize and validate through Pydantic
                        plan = self._build_plan_from_dict(data, mode, f"groq-{model_name}-key{idx+1}")
                        logger.info(
                            "Groq semantic query expansion succeeded via key #%d (%s): %d keywords expanded",
                            idx + 1,
                            model_name,
                            len(plan.expanded_keywords),
                        )
                        return plan

                except Exception as exc:
                    logger.warning(
                        "Groq key #%d with model %s failed: %s. Rotating to next candidate...",
                        idx + 1,
                        model_name,
                        exc,
                    )

        # ── Tier 3: Local Ollama Fallback ────────────────────────────────────
        if ollama_client.is_available():
            try:
                logger.info("Attempting local Ollama query parsing (llama3.1:8b)...")
                prompt_content = f"Target Mode: {mode}\nUser Query: {clean_query}\nReturn JSON."
                data = await ollama_client.generate_structured(
                    prompt=prompt_content,
                    system=SYSTEM_PROMPT,
                    temperature=0.0,
                    num_ctx=2048,
                    timeout=4.0,
                )
                if data and isinstance(data, dict):
                    plan = self._build_plan_from_dict(data, mode, "ollama-llama3.1:8b")
                    logger.info("Local Ollama semantic expansion succeeded")
                    return plan
            except Exception as exc:
                logger.warning("Local Ollama query parsing failed: %s", exc)

        # ── Tier 4: Deterministic Regex Heuristic Engine ─────────────────────
        logger.info("Engaging deterministic regex heuristic query plan for '%s'", clean_query)
        return self._heuristic_fallback(clean_query, mode)

    def _build_plan_from_dict(
        self,
        data: Dict[str, Any],
        mode: str,
        source_model: str,
    ) -> ParsedSearchPlan:
        """Sanitizes raw JSON dictionary and instantiates ParsedSearchPlan."""
        # Normalize target mode
        plan_mode = str(data.get("mode", mode)).strip().lower()
        if plan_mode not in ("company", "people"):
            plan_mode = "people" if mode == "people" else "company"

        # Expanded keywords
        raw_keywords = data.get("expanded_keywords") or []
        if isinstance(raw_keywords, str):
            raw_keywords = [raw_keywords]
        expanded_keywords = [str(k).strip() for k in raw_keywords if str(k).strip()]

        # NAICS codes
        raw_naics = data.get("naics_codes") or []
        if isinstance(raw_naics, str):
            raw_naics = [raw_naics]
        naics_codes = [re.sub(r"[^\d]", "", str(n)) for n in raw_naics if str(n).strip()]
        naics_codes = [n for n in naics_codes if len(n) >= 2]

        # States
        raw_states = data.get("states") or []
        if isinstance(raw_states, str):
            raw_states = [raw_states]
        normalized_states: List[str] = []
        for s in raw_states:
            s_clean = str(s).strip().upper()
            if len(s_clean) == 2 and s_clean in US_STATE_MAP.values():
                normalized_states.append(s_clean)
            elif s_clean.lower() in US_STATE_MAP:
                normalized_states.append(US_STATE_MAP[s_clean.lower()])

        # Cities
        raw_cities = data.get("cities") or []
        if isinstance(raw_cities, str):
            raw_cities = [raw_cities]
        cities = [str(c).strip() for c in raw_cities if str(c).strip()]

        # Titles & Seniorities
        raw_titles = data.get("target_titles") or []
        if isinstance(raw_titles, str):
            raw_titles = [raw_titles]
        target_titles = [str(t).strip() for t in raw_titles if str(t).strip()]

        raw_sen = data.get("seniority_tiers") or []
        if isinstance(raw_sen, str):
            raw_sen = [raw_sen]
        seniority_tiers = [str(sn).strip().upper() for sn in raw_sen if str(sn).strip()]

        # Departments
        raw_deps = data.get("departments") or []
        if isinstance(raw_deps, str):
            raw_deps = [raw_deps]
        departments = [str(d).strip().upper() for d in raw_deps if str(d).strip()]

        # Technologies
        raw_tech = data.get("technologies") or []
        if isinstance(raw_tech, str):
            raw_tech = [raw_tech]
        technologies = [str(t).strip() for t in raw_tech if str(t).strip()]

        # Verified Email & Direct Phone
        require_verified_email = bool(data.get("require_verified_email", False))
        require_direct_phone = bool(data.get("require_direct_phone", False))

        # Summary
        summary = str(data.get("assistant_summary", "")).strip()
        if not summary:
            summary = f"Searching {plan_mode} records matching query criteria."

        return ParsedSearchPlan(
            mode=plan_mode,  # type: ignore
            expanded_keywords=expanded_keywords,
            naics_codes=naics_codes,
            states=normalized_states,
            cities=cities,
            countries=["US"],
            target_titles=target_titles,
            seniority_tiers=seniority_tiers,
            departments=departments,
            technologies=technologies,
            require_verified_email=require_verified_email,
            require_direct_phone=require_direct_phone,
            min_headcount=data.get("min_headcount"),
            max_headcount=data.get("max_headcount"),
            assistant_summary=summary,
            source_model=source_model,
        )

    def _heuristic_fallback(self, query: str, mode: str) -> ParsedSearchPlan:
        """Deterministic entity extraction when all LLM services are offline."""
        q_lower = query.lower()

        # Extract states
        states: List[str] = []
        for state_name, code in US_STATE_MAP.items():
            if re.search(r"\b" + re.escape(state_name) + r"\b", q_lower):
                if code not in states:
                    states.append(code)
        for code in US_STATE_MAP.values():
            if re.search(r"\b" + code + r"\b", query):
                if code not in states:
                    states.append(code)

        # Extract seniorities
        seniority_tiers: List[str] = []
        for term, tier in SENIORITY_KEYWORDS.items():
            if re.search(r"\b" + re.escape(term) + r"\b", q_lower):
                if tier not in seniority_tiers:
                    seniority_tiers.append(tier)

        # Extract departments
        departments: List[str] = []
        for term, dep in DEPARTMENT_KEYWORDS.items():
            if re.search(r"\b" + re.escape(term) + r"\b", q_lower):
                if dep not in departments:
                    departments.append(dep)

        # Extract tech
        technologies: List[str] = []
        for tech in COMMON_TECH_STACKS:
            if re.search(r"\b" + re.escape(tech) + r"\b", q_lower):
                technologies.append(tech.title())

        # Expanded keywords & NAICS codes based on query terms
        expanded_keywords: List[str] = []
        naics_codes: List[str] = []
        for term, codes in COMMON_NAICS_VERTICALS.items():
            if term in q_lower:
                naics_codes.extend(codes)
                if term in ("homecare", "home care", "eldercare"):
                    expanded_keywords.extend([
                        "home health care", "senior care", "elderly assistance",
                        "skilled nursing", "assisted living", "personal care aide",
                        "in-home hospice", "caregiving services"
                    ])
                elif term in ("software", "saas"):
                    expanded_keywords.extend([
                        "b2b saas", "cloud software", "enterprise software",
                        "information technology", "software engineering"
                    ])

        # Email / phone requirements
        require_verified_email = any(w in q_lower for w in ["email", "emails", "deliverable", "contact details"])
        require_direct_phone = any(w in q_lower for w in ["phone", "direct dial", "mobile", "cell", "call"])

        # Construct assistant summary
        parts = []
        if expanded_keywords:
            parts.append(f"{expanded_keywords[0]} industry")
        if states:
            parts.append(f"in {', '.join(states)}")
        if seniority_tiers:
            parts.append(f"({', '.join(seniority_tiers)})")
        if require_verified_email:
            parts.append("with verified emails")

        summary = f"Searching for {' '.join(parts) if parts else query}."

        return ParsedSearchPlan(
            mode="people" if mode == "people" else "company",  # type: ignore
            expanded_keywords=list(set(expanded_keywords)),
            naics_codes=list(set(naics_codes)),
            states=states,
            cities=[],
            countries=["US"],
            target_titles=[],
            seniority_tiers=seniority_tiers,
            departments=departments,
            technologies=technologies,
            require_verified_email=require_verified_email,
            require_direct_phone=require_direct_phone,
            min_headcount=None,
            max_headcount=None,
            assistant_summary=summary,
            source_model="deterministic-regex-heuristic",
        )


# Global singleton instance
groq_search_interpreter = GroqSearchInterpreter()

__all__ = [
    "ParsedSearchPlan",
    "GroqSearchInterpreter",
    "groq_search_interpreter",
]
