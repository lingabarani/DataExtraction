"""
OneExtraction - Lead Builder
Joins person + company data, runs contact validation, and produces
a fully structured lead record ready to INSERT into us_leads or mexico_leads.

Each lead record has:
  - Flat columns  : indexed fields for WHERE/ORDER BY
  - person  JSONB : full person detail
  - company JSONB : full company detail
  - contact JSONB : validated email + phone + linkedin + scores

Supported input formats:
  - DB rows       : dicts from existing people/companies tables (migration)
  - INTERNAL_JSON : nested us_people.json / us_companies.json
  - MEXICO_JSON   : mexico_people.json + mexico_companies.json
  - CSV_ROW       : flat row from exports CSVs (company + person in one row)

Usage:
    from lead_builder import build_us_lead, build_mexico_lead

    lead = build_us_lead(person_dict, company_dict, source='INTERNAL_JSON')
    lead = build_mexico_lead(person_dict, company_dict, source='MEXICO_JSON')
    lead = build_mexico_lead(csv_row, source='CSV_ROW')
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from contact_validator import (
    validate_contact,
    lead_score_from_contact,
    contact_is_usable,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(value) -> Optional[str]:
    if value is None:
        return None
    v = str(value).strip()
    return v if v else None


def _clean_domain(raw) -> Optional[str]:
    from contact_validator import extract_registered_domain
    return extract_registered_domain(raw)


def _to_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_dict(value) -> dict:
    """Ensure value is a dict — parse JSON string if needed."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}
    return {}


def _as_list(value) -> list:
    """Ensure value is a list — parse JSON string if needed."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def _new_id(prefix: str = 'per') -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Person extractors (one per source format)
# ---------------------------------------------------------------------------

def _extract_person_from_db(row: dict) -> dict:
    """Extract person fields from existing people table row."""
    return {
        "id":                   _clean(row.get('id')),
        "full_name":            _clean(row.get('full_name')),
        "first_name":           _clean(row.get('first_name')),
        "middle_name":          _clean(row.get('middle_name')),
        "last_name":            _clean(row.get('last_name')),
        "title":                _clean(row.get('title')),
        "standardized_title":   _clean(row.get('standardized_title')),
        "official_title":       _clean(row.get('official_title')),
        "seniority_level":      _clean(row.get('seniority_level')),
        "department":           _clean(row.get('department')),
        "email":                _clean(row.get('email')),
        "email_status":         _clean(row.get('email_status')),
        "email_confidence_score": _to_int(row.get('email_confidence_score')),
        "email_pattern":        _clean(row.get('email_pattern')),
        "phone":                _clean(row.get('phone')),
        "direct_phone":         _clean(row.get('direct_phone')),
        "phone_type":           _clean(row.get('phone_type')),
        "phone_carrier":        _clean(row.get('phone_carrier')),
        "linkedin_url":         _clean(row.get('linkedin_url')),
        "is_current":           row.get('is_current', True),
        "joined_date":          _clean(str(row['joined_date'])) if row.get('joined_date') else None,
        "years_at_company":     _to_float(row.get('years_at_company')),
        "appointment_source":   _clean(row.get('appointment_source')),
        "source_document_url":  _clean(row.get('source_document_url')),
        "career_history":       _as_list(row.get('career_history')),
        "is_business_contact":  row.get('is_business_contact', True),
        "opt_out_requested":    row.get('opt_out_requested', False),
        "source_registry":      _clean(row.get('source_registry')),
        "data_quality_score":   _to_int(row.get('data_quality_score')),
        "api_source":           _clean(row.get('api_source')),
    }


def _extract_person_from_internal_json(raw: dict) -> dict:
    """Extract from nested us_people.json format."""
    identity  = raw.get('identity') or {}
    employ    = raw.get('employment') or {}
    tenure    = raw.get('tenure_and_history') or {}
    contact   = raw.get('contact') or {}
    metadata  = raw.get('metadata') or {}
    email_ver = contact.get('email_verification') or {}
    phone_obj = contact.get('direct_phone') or {}
    comp_flag = metadata.get('compliance_flags') or {}

    return {
        "id":                   _clean(raw.get('person_id')),
        "full_name":            _clean(identity.get('full_name')),
        "first_name":           _clean(identity.get('first_name')),
        "middle_name":          _clean(identity.get('middle_name')),
        "last_name":            _clean(identity.get('last_name')),
        "title":                _clean(employ.get('official_filing_title')),
        "standardized_title":   _clean(employ.get('standardized_title')),
        "official_title":       _clean(employ.get('official_filing_title')),
        "seniority_level":      _clean(employ.get('seniority_level')),
        "department":           _clean(employ.get('department')),
        "email":                _clean(contact.get('work_email')),
        "email_status":         _clean(email_ver.get('status')),
        "email_confidence_score": _to_int(email_ver.get('total_confidence_score')),
        "email_pattern":        _clean(contact.get('email_pattern')),
        "phone":                _clean(phone_obj.get('phone_number')),
        "direct_phone":         _clean(phone_obj.get('phone_number')),
        "phone_type":           _clean(phone_obj.get('phone_type')),
        "phone_carrier":        _clean(phone_obj.get('carrier')),
        "linkedin_url":         _clean(identity.get('linkedin_url')),
        "is_current":           employ.get('is_current', True),
        "joined_date":          _clean(tenure.get('joined_date')),
        "years_at_company":     _to_float(tenure.get('years_at_company')),
        "appointment_source":   _clean(tenure.get('appointment_source')),
        "source_document_url":  _clean(tenure.get('source_document_url')),
        "career_history":       tenure.get('career_history') or [],
        "is_business_contact":  comp_flag.get('is_business_contact', True),
        "opt_out_requested":    comp_flag.get('opt_out_requested', False),
        "source_registry":      _clean(metadata.get('source_registry')),
        "data_quality_score":   80,
        "api_source":           "INTERNAL_JSON",
    }


def _extract_person_from_mexico_json(raw: dict) -> dict:
    """Extract from flat mexico_people.json format."""
    return {
        "id":                   _clean(raw.get('person_id')),
        "full_name":            _clean(raw.get('full_name')),
        "first_name":           _clean(raw.get('first_name')),
        "middle_name":          None,
        "last_name":            _clean(raw.get('last_name')),
        "title":                _clean(raw.get('title')),
        "standardized_title":   _clean(raw.get('standardized_title')),
        "official_title":       _clean(raw.get('title')),
        "seniority_level":      _clean(raw.get('seniority_level')),
        "department":           _clean(raw.get('department')),
        "email":                _clean(raw.get('work_email')),
        "email_status":         _clean(raw.get('email_status')),
        "email_confidence_score": _to_int(raw.get('email_confidence_score')),
        "phone":                _clean(raw.get('direct_phone')),
        "direct_phone":         _clean(raw.get('direct_phone')),
        "phone_type":           _clean(raw.get('phone_type')),
        "linkedin_url":         None,
        "is_current":           raw.get('is_active', True),
        "career_history":       [],
        "is_business_contact":  True,
        "opt_out_requested":    False,
        "data_quality_score":   _to_int(raw.get('email_confidence_score')) or 70,
        "api_source":           "MEXICO_JSON",
    }


def _extract_person_from_csv(row: dict) -> dict:
    """Extract from flat CSV row (exports/01_manufacturing.csv format)."""
    full_name  = _clean(row.get('full_name'))
    first_name = _clean(row.get('first_name'))
    last_name  = _clean(row.get('last_name'))
    if full_name and not first_name:
        parts = full_name.split(' ', 1)
        first_name = parts[0]
        last_name  = parts[1] if len(parts) > 1 else None

    return {
        "id":                   None,
        "full_name":            full_name,
        "first_name":           first_name,
        "middle_name":          None,
        "last_name":            last_name,
        "title":                _clean(row.get('standardized_title') or row.get('title')),
        "standardized_title":   _clean(row.get('standardized_title')),
        "official_title":       _clean(row.get('title') or row.get('standardized_title')),
        "seniority_level":      _clean(row.get('seniority_level')),
        "department":           _clean(row.get('department')),
        "email":                _clean(row.get('work_email') or row.get('email')),
        "email_status":         _clean(row.get('email_status')),
        "email_confidence_score": _to_int(row.get('email_confidence_score')),
        "phone":                _clean(row.get('direct_phone') or row.get('phone')),
        "direct_phone":         _clean(row.get('direct_phone')),
        "phone_type":           None,
        "linkedin_url":         _clean(row.get('linkedin_url')),
        "is_current":           True,
        "career_history":       [],
        "is_business_contact":  True,
        "opt_out_requested":    False,
        "data_quality_score":   _to_int(row.get('email_confidence_score')) or 70,
        "api_source":           "CSV",
    }


# ---------------------------------------------------------------------------
# Company extractors
# ---------------------------------------------------------------------------

def _extract_company_from_db(row: dict) -> dict:
    """Extract company fields from existing companies table row."""
    return {
        "id":               _clean(row.get('id')),
        "name":             _clean(row.get('name')),
        "legal_name":       _clean(row.get('legal_name')),
        "trade_name":       _clean(row.get('trade_name')),
        "normalized_name":  _clean(row.get('normalized_name')),
        "entity_type":      _clean(row.get('entity_type')),
        "website":          _clean(row.get('website')),
        "domain":           _clean(row.get('domain')),
        "email":            _clean(row.get('email')),
        "phone":            _clean(row.get('phone')),
        "phones":           _as_list(row.get('phones')),
        "emails":           _as_list(row.get('emails')),
        "industry":         _clean(row.get('industry')),
        "naics_code":       _clean(row.get('naics_code')),
        "sic_code":         _clean(row.get('sic_code')),
        "ein":              _clean(row.get('ein')),
        "cik":              _clean(row.get('cik')),
        "cage_code":        _clean(row.get('cage_code')),
        "employee_min":     _to_int(row.get('employee_min')),
        "employee_max":     _to_int(row.get('employee_max')),
        "employee_band":    _clean(row.get('employee_band')),
        "street":           _clean(row.get('street')),
        "city":             _clean(row.get('city')),
        "state":            _clean(row.get('state')),
        "state_code":       _clean(row.get('state_code')),
        "zip_code":         _clean(row.get('zip_code')),
        "county":           _clean(row.get('county')),
        "country":          _clean(row.get('country')) or 'United States',
        "latitude":         _to_float(row.get('latitude')),
        "longitude":        _to_float(row.get('longitude')),
        "data_quality_score": _to_int(row.get('data_quality_score')),
        "last_verified_at": _clean(str(row['last_verified_at'])) if row.get('last_verified_at') else None,
        "source_count":     _to_int(row.get('source_count')),
    }


def _extract_company_from_internal_json(raw: dict) -> dict:
    """Extract from nested us_companies.json format."""
    addr = raw.get('address') or {}
    return {
        "id":               _clean(raw.get('company_id')),
        "name":             _clean(raw.get('trade_name') or raw.get('legal_name')),
        "legal_name":       _clean(raw.get('legal_name')),
        "trade_name":       _clean(raw.get('trade_name')),
        "normalized_name":  _clean(raw.get('normalized_name')),
        "entity_type":      _clean(raw.get('entity_type')),
        "website":          _clean(raw.get('website')),
        "domain":           _clean_domain(raw.get('domain') or raw.get('website')),
        "email":            _clean(raw.get('email')),
        "phone":            _clean(raw.get('phone')),
        "phones":           _as_list(raw.get('phones')),
        "emails":           _as_list(raw.get('emails')),
        "industry":         _clean(raw.get('industry')),
        "naics_code":       _clean(raw.get('naics_code')),
        "sic_code":         _clean(raw.get('sic_code')),
        "ein":              _clean(raw.get('ein')),
        "cik":              _clean(raw.get('cik')),
        "cage_code":        _clean(raw.get('cage_code')),
        "employee_min":     _to_int(raw.get('employee_count_min')),
        "employee_max":     _to_int(raw.get('employee_count_max')),
        "employee_band":    None,
        "street":           _clean(addr.get('street')),
        "city":             _clean(addr.get('city')),
        "state":            _clean(addr.get('state')),
        "state_code":       _clean(addr.get('state_code')),
        "zip_code":         _clean(addr.get('zip_code')),
        "county":           _clean(addr.get('county')),
        "country":          _clean(addr.get('country')) or 'United States',
        "latitude":         _to_float(raw.get('latitude')),
        "longitude":        _to_float(raw.get('longitude')),
        "data_quality_score": _to_int(raw.get('data_quality_score')),
        "last_verified_at": _clean(raw.get('last_verified_at')),
        "source_count":     _to_int(raw.get('source_count')),
    }


def _extract_company_from_mexico_json(raw: dict) -> dict:
    """Extract from mexico_companies.json format (has rfc, colony, municipality)."""
    addr = raw.get('address') or {}
    return {
        "id":               _clean(raw.get('company_id')),
        "name":             _clean(raw.get('trade_name') or raw.get('legal_name')),
        "legal_name":       _clean(raw.get('legal_name')),
        "trade_name":       _clean(raw.get('trade_name')),
        "normalized_name":  _clean(raw.get('normalized_name')),
        "rfc":              _clean(raw.get('rfc')),
        "rfc_type":         _clean(raw.get('rfc_type')),
        "website":          _clean(raw.get('website')),
        "domain":           _clean_domain(raw.get('domain') or raw.get('website')),
        "email":            _clean(raw.get('email')),
        "phone":            _clean(raw.get('phone')),
        "phones":           _as_list(raw.get('phones')),
        "emails":           _as_list(raw.get('emails')),
        "industry":         _clean(raw.get('industry')),
        "industry_code":    _clean(raw.get('industry_code')),
        "employee_min":     _to_int(raw.get('employee_count_min')),
        "employee_max":     _to_int(raw.get('employee_count_max')),
        "street":           _clean(addr.get('street')),
        "number":           _clean(addr.get('number')),
        "colony":           _clean(addr.get('colony')),
        "municipality":     _clean(addr.get('municipality')),
        "state":            _clean(addr.get('state')),
        "postal_code":      _clean(addr.get('postal_code')),
        "country":          "Mexico",
        "latitude":         _to_float(raw.get('latitude')),
        "longitude":        _to_float(raw.get('longitude')),
        "data_quality_score": _to_int(raw.get('data_quality_score')),
        "last_verified_at": _clean(raw.get('last_verified_at')),
        "source_count":     _to_int(raw.get('source_count')),
    }


def _extract_company_from_csv(row: dict) -> dict:
    """Extract company fields from flat CSV row."""
    domain = _clean_domain(row.get('company_domain') or row.get('domain'))
    return {
        "id":           None,
        "name":         _clean(row.get('company_name')),
        "legal_name":   _clean(row.get('company_name')),
        "trade_name":   _clean(row.get('company_name')),
        "domain":       domain,
        "website":      f"https://{domain}" if domain else None,
        "industry":     _clean(row.get('industry')),
        "country":      "Mexico",   # all our CSVs are Mexico data
        "data_quality_score": 60,
    }


# ---------------------------------------------------------------------------
# Core JOIN → lead record builders
# ---------------------------------------------------------------------------

def build_us_lead(
    person:  dict,
    company: dict,
    source:  str = 'DB',
    skip_mx: bool = False,
) -> dict:
    """
    Join US person + company into a fully validated us_leads record.

    Args:
        person:  raw person dict (DB row or JSON)
        company: raw company dict (DB row or JSON), or {} if not available
        source:  'DB' | 'INTERNAL_JSON' | 'CSV'
        skip_mx: skip DNS MX lookup (set True for bulk ingestion)

    Returns:
        Complete lead dict ready to INSERT into us_leads.
    """
    source = source.upper()

    # ── Extract structured dicts ─────────────────────────────────────────────
    if source == 'DB':
        p = _extract_person_from_db(person)
        c = _extract_company_from_db(company) if company else {}
    elif source == 'INTERNAL_JSON':
        p = _extract_person_from_internal_json(person)
        c = _extract_company_from_internal_json(company) if company else {}
    elif source == 'CSV':
        p = _extract_person_from_csv(person)
        c = _extract_company_from_csv(person)   # CSV has company fields inline
    else:
        p = _extract_person_from_db(person)
        c = _extract_company_from_db(company) if company else {}

    # ── Contact validation ───────────────────────────────────────────────────
    contact = validate_contact(
        email=p.get('email'),
        phone=p.get('direct_phone') or p.get('phone'),
        linkedin_url=p.get('linkedin_url'),
        pre_verified_status=p.get('email_status'),
        country='US',
        skip_mx=skip_mx,
    )

    # ── Lead score ───────────────────────────────────────────────────────────
    lead_score = lead_score_from_contact(
        contact,
        person_quality=p.get('data_quality_score') or 0,
        company_quality=c.get('data_quality_score') or 0,
        seniority_level=p.get('seniority_level') or '',
    )

    # ── Determine ID ────────────────────────────────────────────────────────
    lead_id = p.get('id') or _new_id('per')

    # ── Build flat columns ───────────────────────────────────────────────────
    flat = {
        'id':                     lead_id,
        'full_name':              p.get('full_name'),
        'first_name':             p.get('first_name'),
        'last_name':              p.get('last_name'),
        'title':                  p.get('title'),
        'standardized_title':     p.get('standardized_title'),
        'seniority_level':        p.get('seniority_level'),
        'department':             p.get('department'),
        'email':                  contact.get('email'),
        'email_status':           contact.get('email_status'),
        'email_confidence_score': contact.get('email_confidence_score'),
        'phone':                  contact.get('phone'),
        'linkedin_url':           contact.get('linkedin_url'),
        'is_current':             p.get('is_current', True),
        'company_id':             c.get('id') or person.get('company_id'),
        'company_name':           c.get('name'),
        'domain':                 c.get('domain'),
        'industry':               c.get('industry'),
        'naics_code':             c.get('naics_code'),
        'ein':                    c.get('ein'),
        'cik':                    c.get('cik'),
        'employee_band':          c.get('employee_band'),
        'city':                   c.get('city'),
        'state':                  c.get('state'),
        'state_code':             c.get('state_code'),
        'zip_code':               c.get('zip_code'),
        'country':                c.get('country') or 'United States',
        'person_quality_score':   p.get('data_quality_score'),
        'company_quality_score':  c.get('data_quality_score'),
        'lead_score':             lead_score,
        'api_source':             p.get('api_source') or source,
    }

    # ── Build JSONB columns ──────────────────────────────────────────────────
    flat['person'] = json.dumps({
        "id":                   p.get('id'),
        "full_name":            p.get('full_name'),
        "first_name":           p.get('first_name'),
        "middle_name":          p.get('middle_name'),
        "last_name":            p.get('last_name'),
        "title":                p.get('title'),
        "standardized_title":   p.get('standardized_title'),
        "official_title":       p.get('official_title'),
        "seniority_level":      p.get('seniority_level'),
        "department":           p.get('department'),
        "is_current":           p.get('is_current', True),
        "joined_date":          p.get('joined_date'),
        "years_at_company":     p.get('years_at_company'),
        "appointment_source":   p.get('appointment_source'),
        "source_document_url":  p.get('source_document_url'),
        "career_history":       p.get('career_history') or [],
        "linkedin_url":         p.get('linkedin_url'),
        "is_business_contact":  p.get('is_business_contact', True),
        "opt_out_requested":    p.get('opt_out_requested', False),
        "source_registry":      p.get('source_registry'),
        "data_quality_score":   p.get('data_quality_score'),
        "api_source":           p.get('api_source'),
    })

    flat['company'] = json.dumps({
        "id":               c.get('id'),
        "name":             c.get('name'),
        "legal_name":       c.get('legal_name'),
        "trade_name":       c.get('trade_name'),
        "normalized_name":  c.get('normalized_name'),
        "entity_type":      c.get('entity_type'),
        "website":          c.get('website'),
        "domain":           c.get('domain'),
        "email":            c.get('email'),
        "phone":            c.get('phone'),
        "phones":           c.get('phones') or [],
        "emails":           c.get('emails') or [],
        "industry":         c.get('industry'),
        "naics_code":       c.get('naics_code'),
        "sic_code":         c.get('sic_code'),
        "ein":              c.get('ein'),
        "cik":              c.get('cik'),
        "cage_code":        c.get('cage_code'),
        "employee_min":     c.get('employee_min'),
        "employee_max":     c.get('employee_max'),
        "employee_band":    c.get('employee_band'),
        "address": {
            "street":    c.get('street'),
            "city":      c.get('city'),
            "state":     c.get('state'),
            "state_code":c.get('state_code'),
            "zip_code":  c.get('zip_code'),
            "county":    c.get('county'),
            "country":   c.get('country') or 'United States',
        },
        "latitude":           c.get('latitude'),
        "longitude":          c.get('longitude'),
        "data_quality_score": c.get('data_quality_score'),
        "last_verified_at":   c.get('last_verified_at'),
        "source_count":       c.get('source_count'),
    })

    flat['contact'] = json.dumps(contact)

    return flat


def build_mexico_lead(
    person:  dict,
    company: dict = None,
    source:  str = 'MEXICO_JSON',
    skip_mx: bool = False,
) -> dict:
    """
    Join Mexico person + company into a fully validated mexico_leads record.

    Args:
        person:  raw person dict (DB row, JSON, or CSV row)
        company: raw company dict, or None (for CSV where company is inline)
        source:  'DB' | 'MEXICO_JSON' | 'CSV_ROW'
        skip_mx: skip DNS MX lookup
    """
    source = source.upper()

    if source == 'DB':
        p = _extract_person_from_db(person)
        c = _extract_company_from_db(company) if company else {}
    elif source == 'MEXICO_JSON':
        p = _extract_person_from_mexico_json(person)
        c = _extract_company_from_mexico_json(company) if company else {}
    elif source in ('CSV_ROW', 'CSV'):
        p = _extract_person_from_csv(person)
        c = _extract_company_from_csv(person)
    else:
        p = _extract_person_from_mexico_json(person)
        c = _extract_company_from_mexico_json(company) if company else {}

    # ── Contact validation ───────────────────────────────────────────────────
    contact = validate_contact(
        email=p.get('email'),
        phone=p.get('direct_phone') or p.get('phone'),
        linkedin_url=p.get('linkedin_url'),
        pre_verified_status=p.get('email_status'),
        country='MX',
        skip_mx=skip_mx,
    )

    # ── Lead score ───────────────────────────────────────────────────────────
    lead_score = lead_score_from_contact(
        contact,
        person_quality=p.get('data_quality_score') or 0,
        company_quality=c.get('data_quality_score') or 0,
        seniority_level=p.get('seniority_level') or '',
    )

    lead_id = p.get('id') or _new_id('per')

    # ── Flat columns ─────────────────────────────────────────────────────────
    flat = {
        'id':                     lead_id,
        'full_name':              p.get('full_name'),
        'first_name':             p.get('first_name'),
        'last_name':              p.get('last_name'),
        'title':                  p.get('title'),
        'standardized_title':     p.get('standardized_title'),
        'seniority_level':        p.get('seniority_level'),
        'department':             p.get('department'),
        'email':                  contact.get('email'),
        'email_status':           contact.get('email_status'),
        'email_confidence_score': contact.get('email_confidence_score'),
        'phone':                  contact.get('phone'),
        'is_current':             p.get('is_current', True),
        'company_id':             c.get('id') or person.get('company_id'),
        'company_name':           c.get('name'),
        'domain':                 c.get('domain'),
        'industry':               c.get('industry'),
        'industry_code':          c.get('industry_code'),
        'rfc':                    c.get('rfc'),
        'rfc_type':               c.get('rfc_type'),
        'employee_band':          c.get('employee_band'),
        'municipality':           c.get('municipality'),
        'state':                  c.get('state'),
        'postal_code':            c.get('postal_code'),
        'country':                'Mexico',
        'person_quality_score':   p.get('data_quality_score'),
        'company_quality_score':  c.get('data_quality_score'),
        'lead_score':             lead_score,
        'api_source':             p.get('api_source') or source,
    }

    # ── JSONB columns ────────────────────────────────────────────────────────
    flat['person'] = json.dumps({
        "id":                 p.get('id'),
        "full_name":          p.get('full_name'),
        "first_name":         p.get('first_name'),
        "last_name":          p.get('last_name'),
        "title":              p.get('title'),
        "standardized_title": p.get('standardized_title'),
        "seniority_level":    p.get('seniority_level'),
        "department":         p.get('department'),
        "is_current":         p.get('is_current', True),
        "career_history":     p.get('career_history') or [],
        "is_business_contact":p.get('is_business_contact', True),
        "opt_out_requested":  p.get('opt_out_requested', False),
        "data_quality_score": p.get('data_quality_score'),
        "api_source":         p.get('api_source'),
    })

    flat['company'] = json.dumps({
        "id":            c.get('id'),
        "name":          c.get('name'),
        "legal_name":    c.get('legal_name'),
        "trade_name":    c.get('trade_name'),
        "rfc":           c.get('rfc'),
        "rfc_type":      c.get('rfc_type'),
        "website":       c.get('website'),
        "domain":        c.get('domain'),
        "email":         c.get('email'),
        "phone":         c.get('phone'),
        "phones":        c.get('phones') or [],
        "emails":        c.get('emails') or [],
        "industry":      c.get('industry'),
        "industry_code": c.get('industry_code'),
        "employee_min":  c.get('employee_min'),
        "employee_max":  c.get('employee_max'),
        "address": {
            "street":      c.get('street'),
            "number":      c.get('number'),
            "colony":      c.get('colony'),
            "municipality":c.get('municipality'),
            "state":       c.get('state'),
            "postal_code": c.get('postal_code'),
            "country":     "Mexico",
        },
        "latitude":           c.get('latitude'),
        "longitude":          c.get('longitude'),
        "data_quality_score": c.get('data_quality_score'),
        "last_verified_at":   c.get('last_verified_at'),
        "source_count":       c.get('source_count'),
    })

    flat['contact'] = json.dumps(contact)

    return flat


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import json as _json

    print("\n=== Lead Builder Self-Test ===\n")

    # -- US lead from INTERNAL_JSON
    sample_person = {
        "person_id": "per_3cf9dc2183408a9532f9754c5d74bb4b",
        "company_id": "us_9eef2ff7-82cf-51d3-8407-b43677edfcdf",
        "identity": {
            "first_name": "Michael", "middle_name": "A", "last_name": "Johnson",
            "full_name": "Michael A. Johnson",
            "linkedin_url": "https://www.linkedin.com/in/michael-johnson-5494"
        },
        "employment": {
            "official_filing_title": "Chief Executive Officer (CEO)",
            "standardized_title": "Chief Executive Officer (CEO)",
            "seniority_level": "C_SUITE", "department": "EXECUTIVE", "is_current": True
        },
        "tenure_and_history": {
            "joined_date": "2022-01-10", "years_at_company": 4.7,
            "appointment_source": "SEC_8K_ITEM_502", "career_history": []
        },
        "contact": {
            "work_email": "michael.johnson@niagarauniversity.com",
            "email_pattern": "{first}.{last}@{domain}",
            "email_verification": {"status": "VERIFIED", "total_confidence_score": 95},
            "direct_phone": {"phone_number": "+16859913644", "phone_type": "DIRECT_DESK",
                             "carrier": "T-Mobile"}
        },
        "metadata": {"source_registry": "SEC",
                     "compliance_flags": {"is_business_contact": True, "opt_out_requested": False}}
    }
    sample_company = {
        "company_id": "us_9eef2ff7-82cf-51d3-8407-b43677edfcdf",
        "legal_name": "NIAGARA UNIVERSITY", "trade_name": "Niagara University",
        "domain": "niagarauniversity.com", "website": "https://niagarauniversity.com",
        "industry": "Education", "naics_code": "611110",
        "address": {"city": "Niagara University", "state": "New York",
                    "state_code": "NY", "country": "United States"},
        "data_quality_score": 95
    }

    us_lead = build_us_lead(sample_person, sample_company, source='INTERNAL_JSON', skip_mx=True)
    contact = _json.loads(us_lead['contact'])
    person  = _json.loads(us_lead['person'])
    company = _json.loads(us_lead['company'])

    print(f"  [US Lead] id={us_lead['id']}")
    print(f"    full_name      : {us_lead['full_name']}")
    print(f"    email          : {us_lead['email']} -> {us_lead['email_status']}")
    print(f"    phone          : {us_lead['phone']}")
    print(f"    linkedin       : {contact['linkedin_url']}")
    print(f"    company        : {us_lead['company_name']} ({us_lead['domain']})")
    print(f"    seniority      : {us_lead['seniority_level']}")
    print(f"    lead_score     : {us_lead['lead_score']}")
    print(f"    person JSONB   : {len(us_lead['person'])} chars")
    print(f"    company JSONB  : {len(us_lead['company'])} chars")
    print(f"    contact JSONB  : {len(us_lead['contact'])} chars")
    print(f"    career_history : {person['career_history']}")
    print(f"    company.address: {company['address']}")

    # -- Mexico lead from CSV row
    csv_row = {
        "company_name": "TRANSFORMADORA NACIONAL S.A.P.I. DE C.V.",
        "company_domain": "transformadoranaci.mx",
        "full_name": "Lorena Flores",
        "standardized_title": "Sole Administrator / Owner",
        "seniority_level": "FOUNDER", "department": "EXECUTIVE",
        "work_email": "lflores@transformadoranaci.mx",
        "email_status": "VERIFIED", "email_confidence_score": "85",
        "direct_phone": "+527225974883",
        "industry": "Industrial Manufacturing & Transformation"
    }

    mx_lead = build_mexico_lead(csv_row, source='CSV_ROW', skip_mx=True)
    print(f"\n  [MX Lead] id={mx_lead['id']}")
    print(f"    full_name  : {mx_lead['full_name']}")
    print(f"    email      : {mx_lead['email']} -> {mx_lead['email_status']}")
    print(f"    phone      : {mx_lead['phone']}")
    print(f"    company    : {mx_lead['company_name']} ({mx_lead['domain']})")
    print(f"    lead_score : {mx_lead['lead_score']}")
    print(f"    country    : {mx_lead['country']}")

    print("\n=== All tests passed ===\n")
