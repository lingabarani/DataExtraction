"""
OneExtraction — Source Normalizer
Maps raw records from any API or CSV source into our unified DB schema.

Supported sources:
  - INTERNAL_JSON   : our own us_companies.json / us_people.json format
  - CSV             : exports like 01_manufacturing.csv (people + company in one row)
  - PDL             : People Data Labs API response format
  - SEC             : SEC EDGAR bulk/API response format
  - APOLLO          : Apollo.io CSV/API export
  - ZOOMINFO        : ZoomInfo CSV export

Usage:
    from normalizer import normalize_company, normalize_person

    company = normalize_company(raw_record, source='INTERNAL_JSON')
    person  = normalize_person(raw_record,  source='CSV')
"""

import json
import re
from datetime import datetime, timezone


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _clean(value):
    """Strip whitespace, return None for empty strings."""
    if value is None:
        return None
    v = str(value).strip()
    return v if v else None


try:
    import tldextract
    from pathlib import Path
    _EXTRACTOR = tldextract.TLDExtract(
        cache_dir=str(Path.home() / ".cache" / "tldextract"),
        include_psl_private_domains=True
    )
except ImportError:
    _EXTRACTOR = None

try:
    from geo_validator import normalize_postal_code
except ImportError:
    def normalize_postal_code(code, country="US"):
        return str(code).strip() if code else None


def _clean_domain(website_or_domain):
    """Extract registered domain from a URL or domain string using tldextract."""
    if not website_or_domain:
        return None
    d = str(website_or_domain).strip().lower()
    d = re.sub(r'^https?://', '', d)
    d = d.split('/')[0].split('?')[0]
    if _EXTRACTOR:
        ext = _EXTRACTOR(d)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}".lower()
    d = re.sub(r'^www\.', '', d)
    return d if d else None


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().upper() in ('TRUE', '1', 'YES')
    return bool(value) if value is not None else None


def _now():
    return datetime.now(timezone.utc).isoformat()


def _as_json(value):
    """Ensure value is stored as JSON string for JSONB columns."""
    if value is None:
        return '[]'
    if isinstance(value, str):
        return value  # already serialized
    return json.dumps(value)


# ─────────────────────────────────────────────────────────────────────────────
# COMPANY normalizers
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_company_internal_json(raw: dict) -> dict:
    """Maps our own us_companies.json format."""
    addr = raw.get('address') or {}
    phones = raw.get('phones') or []
    emails = raw.get('emails') or []

    return {
        'id':                     _clean(raw.get('company_id')),
        'name':                   _clean(raw.get('trade_name') or raw.get('legal_name')),
        'legal_name':             _clean(raw.get('legal_name')),
        'trade_name':             _clean(raw.get('trade_name')),
        'normalized_name':        _clean(raw.get('normalized_name')),
        'entity_type':            _clean(raw.get('entity_type')),
        'website':                _clean(raw.get('website')),
        'domain':                 _clean_domain(raw.get('domain') or raw.get('website')),
        'email':                  _clean(raw.get('email')),
        'phone':                  _clean(raw.get('phone')),
        'phones':                 _as_json(phones),
        'emails':                 _as_json(emails),
        'industry':               _clean(raw.get('industry')),
        'naics_code':             _clean(raw.get('naics_code')),
        'sic_code':               _clean(raw.get('sic_code')),
        'ein':                    _clean(raw.get('ein')),
        'cik':                    _clean(raw.get('cik')),
        'cage_code':              _clean(raw.get('cage_code')),
        'uei':                    _clean(raw.get('uei')),
        'state_of_incorporation': _clean(raw.get('state_of_incorporation')),
        'street':                 _clean(addr.get('street')),
        'city':                   _clean(addr.get('city')),
        'state':                  _clean(addr.get('state')),
        'state_code':             _clean(addr.get('state_code')),
        'zip_code':               normalize_postal_code(addr.get('zip_code'), raw.get('country') or 'US'),
        'county':                 _clean(addr.get('county')),
        'country':                _clean(addr.get('country')) or 'United States',
        'latitude':               _to_float(raw.get('latitude')),
        'longitude':              _to_float(raw.get('longitude')),
        'employee_min':           _to_int(raw.get('employee_count_min')),
        'employee_max':           _to_int(raw.get('employee_count_max')),
        'employee_band':          _clean(raw.get('employee_band')),
        'employee_count_source':  _clean(raw.get('employee_count_source')),
        'source_count':           _to_int(raw.get('source_count')) or 1,
        'data_quality_score':     _to_int(raw.get('data_quality_score')),
        'last_verified_at':       _clean(raw.get('last_verified_at')),
        'api_source':             'INTERNAL_JSON',
        'source':                 'INTERNAL_JSON',
        'raw_payload':            _as_json(raw),
    }


def _normalize_company_csv(raw: dict) -> dict:
    """Maps CSV rows that contain company columns (domain, company_name, industry)."""
    domain = _clean_domain(raw.get('company_domain') or raw.get('domain') or raw.get('website'))
    return {
        'id':                 None,   # will be generated by deduplicator
        'name':               _clean(raw.get('company_name') or raw.get('name')),
        'legal_name':         _clean(raw.get('company_name') or raw.get('legal_name')),
        'trade_name':         _clean(raw.get('company_name')),
        'normalized_name':    _clean((raw.get('company_name') or '').upper()),
        'website':            _clean(raw.get('website') or (f'https://{domain}' if domain else None)),
        'domain':             domain,
        'email':              None,
        'phone':              None,
        'phones':             '[]',
        'emails':             '[]',
        'industry':           _clean(raw.get('industry')),
        'naics_code':         None,
        'state_code':         _clean(raw.get('state_code')),
        'country':            _clean(raw.get('country')) or 'United States',
        'data_quality_score': _to_int(raw.get('data_quality_score')) or 60,
        'api_source':         'CSV',
        'source':             'CSV',
        'raw_payload':        _as_json(raw),
    }


def _normalize_company_pdl(raw: dict) -> dict:
    """Maps People Data Labs company/org fields."""
    website = _clean(raw.get('website'))
    return {
        'id':                 _clean(raw.get('id')),
        'name':               _clean(raw.get('display_name') or raw.get('name')),
        'legal_name':         _clean(raw.get('legal_name') or raw.get('name')),
        'trade_name':         _clean(raw.get('display_name')),
        'normalized_name':    _clean((raw.get('name') or '').upper()),
        'website':            website,
        'domain':             _clean_domain(raw.get('website')),
        'email':              None,
        'phone':              _clean(raw.get('phone')),
        'phones':             '[]',
        'emails':             '[]',
        'industry':           _clean(raw.get('industry')),
        'naics_code':         None,
        'city':               _clean(raw.get('location_locality') or raw.get('city')),
        'state':              _clean(raw.get('location_region') or raw.get('state')),
        'state_code':         _clean(raw.get('location_region_abbreviation')),
        'country':            _clean(raw.get('location_country')) or 'United States',
        'employee_min':       _to_int(raw.get('employee_count_range_min')),
        'employee_max':       _to_int(raw.get('employee_count_range_max')),
        'data_quality_score': _to_int(raw.get('confidence')) or 70,
        'api_source':         'PDL',
        'source':             'PDL',
        'raw_payload':        _as_json(raw),
    }


def _normalize_company_sec(raw: dict) -> dict:
    """Maps SEC EDGAR company fields."""
    return {
        'id':                 None,
        'name':               _clean(raw.get('name') or raw.get('company_name')),
        'legal_name':         _clean(raw.get('name') or raw.get('company_name')),
        'normalized_name':    _clean((raw.get('name') or '').upper()),
        'cik':                _clean(raw.get('cik')),
        'ein':                _clean(raw.get('ein')),
        'sic_code':           _clean(raw.get('sic')),
        'state_of_incorporation': _clean(raw.get('stateOfIncorporation')),
        'state_code':         _clean(raw.get('stateOfIncorporation')),
        'country':            'United States',
        'data_quality_score': 85,   # SEC data is high quality
        'api_source':         'SEC',
        'source':             'SEC',
        'raw_payload':        _as_json(raw),
    }


def _normalize_company_apollo(raw: dict) -> dict:
    """Maps Apollo.io CSV/API export columns."""
    return {
        'id':                 None,
        'name':               _clean(raw.get('Company') or raw.get('company_name')),
        'legal_name':         _clean(raw.get('Company')),
        'normalized_name':    _clean((raw.get('Company') or '').upper()),
        'website':            _clean(raw.get('Website') or raw.get('website')),
        'domain':             _clean_domain(raw.get('Website') or raw.get('website')),
        'phone':              _clean(raw.get('Company Phone')),
        'industry':           _clean(raw.get('Industry')),
        'city':               _clean(raw.get('Company City')),
        'state':              _clean(raw.get('Company State')),
        'state_code':         _clean(raw.get('Company State')),
        'country':            _clean(raw.get('Company Country')) or 'United States',
        'employee_band':      _clean(raw.get('# Employees')),
        'data_quality_score': 65,
        'api_source':         'APOLLO',
        'source':             'APOLLO',
        'raw_payload':        _as_json(raw),
    }


def _normalize_company_zoominfo(raw: dict) -> dict:
    """Maps ZoomInfo CSV export columns."""
    return {
        'id':                 None,
        'name':               _clean(raw.get('Company Name')),
        'legal_name':         _clean(raw.get('Company Name')),
        'normalized_name':    _clean((raw.get('Company Name') or '').upper()),
        'website':            _clean(raw.get('Website')),
        'domain':             _clean_domain(raw.get('Website')),
        'phone':              _clean(raw.get('Company Phone')),
        'industry':           _clean(raw.get('Primary Industry')),
        'naics_code':         _clean(raw.get('NAICS Code')),
        'city':               _clean(raw.get('City')),
        'state':              _clean(raw.get('State')),
        'state_code':         _clean(raw.get('State')),
        'zip_code':           _clean(raw.get('Zip Code')),
        'country':            _clean(raw.get('Country')) or 'United States',
        'employee_min':       _to_int(raw.get('Employees')),
        'data_quality_score': 70,
        'api_source':         'ZOOMINFO',
        'source':             'ZOOMINFO',
        'raw_payload':        _as_json(raw),
    }


# ─────────────────────────────────────────────────────────────────────────────
# PERSON normalizers
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_person_internal_json(raw: dict) -> dict:
    """Maps our own us_people.json (nested) format."""
    identity  = raw.get('identity')  or {}
    employ    = raw.get('employment') or {}
    tenure    = raw.get('tenure_and_history') or {}
    contact   = raw.get('contact')   or {}
    metadata  = raw.get('metadata')  or {}
    email_ver = contact.get('email_verification') or {}
    phone_obj = contact.get('direct_phone') or {}
    compliance = metadata.get('compliance_flags') or {}

    return {
        'id':                    _clean(raw.get('person_id')),
        'company_id':            _clean(raw.get('company_id')),
        'full_name':             _clean(identity.get('full_name')),
        'first_name':            _clean(identity.get('first_name')),
        'middle_name':           _clean(identity.get('middle_name')),
        'last_name':             _clean(identity.get('last_name')),
        'linkedin_url':          _clean(identity.get('linkedin_url')),
        'title':                 _clean(employ.get('official_filing_title')),
        'official_title':        _clean(employ.get('official_filing_title')),
        'standardized_title':    _clean(employ.get('standardized_title')),
        'seniority_level':       _clean(employ.get('seniority_level')),
        'department':            _clean(employ.get('department')),
        'is_current':            _to_bool(employ.get('is_current', True)),
        'joined_date':           _clean(tenure.get('joined_date')),
        'years_at_company':      _to_float(tenure.get('years_at_company')),
        'appointment_source':    _clean(tenure.get('appointment_source')),
        'source_document_url':   _clean(tenure.get('source_document_url')),
        'career_history':        _as_json(tenure.get('career_history', [])),
        'email':                 _clean(contact.get('work_email')),
        'email_pattern':         _clean(contact.get('email_pattern')),
        'email_status':          _clean(email_ver.get('status')),
        'email_confidence_score':_to_int(email_ver.get('total_confidence_score')),
        'email_last_validated_at':_clean(email_ver.get('last_validated_at')),
        'phone':                 _clean(phone_obj.get('phone_number')),
        'direct_phone':          _clean(phone_obj.get('phone_number')),
        'phone_type':            _clean(phone_obj.get('phone_type')),
        'phone_carrier':         _clean(phone_obj.get('carrier')),
        'is_business_contact':   _to_bool(compliance.get('is_business_contact', True)),
        'opt_out_requested':     _to_bool(compliance.get('opt_out_requested', False)),
        'source_registry':       _clean(metadata.get('source_registry')),
        'api_source':            'INTERNAL_JSON',
        'data_quality_score':    80,
        'raw_payload':           _as_json(raw),
    }


def _normalize_person_csv(raw: dict) -> dict:
    """Maps flat CSV rows (exports like 01_manufacturing.csv)."""
    full_name  = _clean(raw.get('full_name'))
    first_name = _clean(raw.get('first_name'))
    last_name  = _clean(raw.get('last_name'))

    # Try to split full_name if first/last not provided
    if full_name and not first_name:
        parts = full_name.split(' ', 1)
        first_name = parts[0]
        last_name  = parts[1] if len(parts) > 1 else None

    return {
        'id':                    None,   # generated by deduplicator
        'company_id':            None,   # resolved by ingest_data.py from domain
        'full_name':             full_name,
        'first_name':            first_name,
        'middle_name':           None,
        'last_name':             last_name,
        'linkedin_url':          _clean(raw.get('linkedin_url')),
        'title':                 _clean(raw.get('standardized_title') or raw.get('title')),
        'official_title':        _clean(raw.get('title') or raw.get('standardized_title')),
        'standardized_title':    _clean(raw.get('standardized_title')),
        'seniority_level':       _clean(raw.get('seniority_level')),
        'department':            _clean(raw.get('department')),
        'is_current':            True,
        'email':                 _clean(raw.get('work_email') or raw.get('email')),
        'email_status':          _clean(raw.get('email_status')),
        'email_confidence_score':_to_int(raw.get('email_confidence_score')),
        'phone':                 _clean(raw.get('direct_phone') or raw.get('phone')),
        'direct_phone':          _clean(raw.get('direct_phone')),
        'is_business_contact':   True,
        'opt_out_requested':     False,
        'api_source':            'CSV',
        'data_quality_score':    _to_int(raw.get('email_confidence_score')) or 70,
        'raw_payload':           _as_json(raw),
    }


def _normalize_person_pdl(raw: dict) -> dict:
    """Maps People Data Labs person API response."""
    experience = raw.get('experience') or []
    current_job = next((e for e in experience if e.get('is_primary')), {})

    return {
        'id':                    _clean(raw.get('id')),
        'company_id':            None,   # resolved from company domain
        'full_name':             _clean(raw.get('full_name')),
        'first_name':            _clean(raw.get('first_name')),
        'middle_name':           _clean(raw.get('middle_initial')),
        'last_name':             _clean(raw.get('last_name')),
        'linkedin_url':          _clean(raw.get('linkedin_url')),
        'title':                 _clean(raw.get('job_title')),
        'official_title':        _clean(raw.get('job_title')),
        'standardized_title':    _clean(raw.get('job_title_role')),
        'seniority_level':       _clean((raw.get('job_title_levels') or [''])[0]),
        'department':            _clean(raw.get('job_title_role')),
        'is_current':            True,
        'email':                 _clean(raw.get('work_email') or raw.get('email')),
        'email_status':          'GUESSED',
        'phone':                 _clean(raw.get('mobile_phone')),
        'direct_phone':          _clean(raw.get('mobile_phone')),
        'is_business_contact':   True,
        'opt_out_requested':     False,
        'api_source':            'PDL',
        'source_registry':       'PDL',
        'data_quality_score':    _to_int(raw.get('likelihood', 7)) * 10,
        'raw_payload':           _as_json(raw),
    }


def _normalize_person_sec(raw: dict) -> dict:
    """Maps SEC EDGAR executive/officer filing records."""
    return {
        'id':                    None,
        'company_id':            None,
        'full_name':             _clean(raw.get('name')),
        'first_name':            _clean((raw.get('name') or '').split()[0] if raw.get('name') else None),
        'last_name':             _clean(' '.join((raw.get('name') or '').split()[1:]) or None),
        'title':                 _clean(raw.get('position')),
        'official_title':        _clean(raw.get('position')),
        'standardized_title':    _clean(raw.get('position')),
        'seniority_level':       'C_SUITE',
        'department':            'EXECUTIVE',
        'is_current':            _to_bool(raw.get('is_current', True)),
        'joined_date':           _clean(raw.get('appointed_date')),
        'appointment_source':    _clean(raw.get('form_type')),
        'source_document_url':   _clean(raw.get('filing_url')),
        'email':                 None,
        'is_business_contact':   True,
        'opt_out_requested':     False,
        'api_source':            'SEC',
        'source_registry':       'SEC',
        'data_quality_score':    85,
        'raw_payload':           _as_json(raw),
    }


def _normalize_person_apollo(raw: dict) -> dict:
    """Maps Apollo.io CSV/API person export."""
    return {
        'id':                    None,
        'company_id':            None,
        'full_name':             _clean(f"{raw.get('First Name','')} {raw.get('Last Name','')}".strip()),
        'first_name':            _clean(raw.get('First Name')),
        'last_name':             _clean(raw.get('Last Name')),
        'linkedin_url':          _clean(raw.get('LinkedIn URL')),
        'title':                 _clean(raw.get('Title')),
        'official_title':        _clean(raw.get('Title')),
        'standardized_title':    _clean(raw.get('Title')),
        'seniority_level':       _clean(raw.get('Seniority')),
        'department':            _clean(raw.get('Department')),
        'email':                 _clean(raw.get('Email')),
        'email_status':          _clean(raw.get('Email Status')),
        'phone':                 _clean(raw.get('Work Direct Phone') or raw.get('Mobile Phone')),
        'direct_phone':          _clean(raw.get('Work Direct Phone')),
        'is_business_contact':   True,
        'opt_out_requested':     False,
        'api_source':            'APOLLO',
        'data_quality_score':    65,
        'raw_payload':           _as_json(raw),
    }


def _normalize_person_zoominfo(raw: dict) -> dict:
    """Maps ZoomInfo CSV person export."""
    return {
        'id':                    None,
        'company_id':            None,
        'full_name':             _clean(f"{raw.get('First Name','')} {raw.get('Last Name','')}".strip()),
        'first_name':            _clean(raw.get('First Name')),
        'last_name':             _clean(raw.get('Last Name')),
        'linkedin_url':          _clean(raw.get('LinkedIn URL')),
        'title':                 _clean(raw.get('Job Title')),
        'official_title':        _clean(raw.get('Job Title')),
        'standardized_title':    _clean(raw.get('Job Title')),
        'seniority_level':       _clean(raw.get('Management Level')),
        'department':            _clean(raw.get('Department')),
        'email':                 _clean(raw.get('Email Address')),
        'phone':                 _clean(raw.get('Direct Phone Number')),
        'direct_phone':          _clean(raw.get('Direct Phone Number')),
        'is_business_contact':   True,
        'opt_out_requested':     False,
        'api_source':            'ZOOMINFO',
        'data_quality_score':    70,
        'raw_payload':           _as_json(raw),
    }


def _normalize_company_osm(raw: dict) -> dict:
    """
    Maps OpenStreetMap / Overpass extracted business POI record into unified schema.
    Handles both extracted POI dictionary and raw Overpass element.
    """
    tags = raw.get('tags') if isinstance(raw.get('tags'), dict) else {}
    name = (
        raw.get('name')
        or tags.get('name')
        or raw.get('brand')
        or tags.get('brand')
        or raw.get('operator')
        or tags.get('operator')
    )
    website = (
        raw.get('website')
        or tags.get('website')
        or tags.get('contact:website')
        or tags.get('url')
    )
    domain = _clean_domain(raw.get('domain') or website)

    # Address components
    street_num = raw.get('addr:housenumber') or tags.get('addr:housenumber') or ''
    street_name = raw.get('addr:street') or tags.get('addr:street') or ''
    street = f"{street_num} {street_name}".strip() or None
    city = raw.get('addr:city') or tags.get('addr:city')
    state = raw.get('addr:state') or tags.get('addr:state')
    state_code = raw.get('state_code') or raw.get('addr:state') or tags.get('addr:state')
    if state_code and len(state_code) > 2:
        state_code = state_code[:2].upper()
    elif state_code:
        state_code = state_code.upper()

    zip_code = raw.get('addr:postcode') or tags.get('addr:postcode')
    country = raw.get('addr:country') or tags.get('addr:country') or 'United States'

    # Coordinate extraction
    lat = raw.get('latitude') or raw.get('lat')
    lon = raw.get('longitude') or raw.get('lon')

    # Contact info
    phone = raw.get('phone') or tags.get('phone') or tags.get('contact:phone') or raw.get('mobile') or tags.get('contact:mobile')
    email = raw.get('email') or tags.get('email') or tags.get('contact:email')
    phones = [phone] if phone else []
    emails = [email] if email else []

    # Category / Industry mapping
    category_group = raw.get('category_group') or tags.get('category_group') or 'SERVICES'
    category = raw.get('category') or raw.get('osm_value') or tags.get('amenity') or tags.get('shop') or tags.get('office')

    # Compute data quality score: base 55, +15 if phone, +15 if website/domain, +10 if full street address, +5 if coordinates
    score = 55
    if phone: score += 15
    if website: score += 15
    if street and city: score += 10
    if lat and lon: score += 5

    osm_id = raw.get('osm_id') or raw.get('id')
    osm_type = raw.get('osm_type') or raw.get('type') or 'node'
    source_id = f"osm_{osm_type}_{osm_id}" if osm_id else None

    return {
        'id':                     source_id,
        'name':                   _clean(name),
        'legal_name':             _clean(raw.get('operator') or tags.get('operator') or name),
        'trade_name':             _clean(raw.get('brand') or tags.get('brand') or name),
        'normalized_name':        _clean((name or '').upper()),
        'website':                _clean(website),
        'domain':                 domain,
        'email':                  _clean(email),
        'phone':                  _clean(phone),
        'phones':                 _as_json(phones),
        'emails':                 _as_json(emails),
        'industry':               _clean(category_group),
        'category':               _clean(category),
        'naics_code':             None,
        'street':                 _clean(street),
        'city':                   _clean(city),
        'state':                  _clean(state),
        'state_code':             _clean(state_code),
        'zip_code':               _clean(zip_code),
        'country':                _clean(country),
        'latitude':               _to_float(lat),
        'longitude':              _to_float(lon),
        'source_count':           1,
        'data_quality_score':     min(score, 100),
        'api_source':             'OPEN_MAP',
        'source':                 'OPEN_MAP',
        'raw_payload':            _as_json(raw),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

_COMPANY_NORMALIZERS = {
    'INTERNAL_JSON': _normalize_company_internal_json,
    'CSV':           _normalize_company_csv,
    'PDL':           _normalize_company_pdl,
    'SEC':           _normalize_company_sec,
    'APOLLO':        _normalize_company_apollo,
    'ZOOMINFO':      _normalize_company_zoominfo,
    'OPEN_MAP':      _normalize_company_osm,
    'OSM':           _normalize_company_osm,
}

_PERSON_NORMALIZERS = {
    'INTERNAL_JSON': _normalize_person_internal_json,
    'CSV':           _normalize_person_csv,
    'PDL':           _normalize_person_pdl,
    'SEC':           _normalize_person_sec,
    'APOLLO':        _normalize_person_apollo,
    'ZOOMINFO':      _normalize_person_zoominfo,
}


def normalize_company(raw: dict, source: str) -> dict:
    """
    Normalize a raw company record into our unified schema.

    Args:
        raw:    raw dict from the source (API response or CSV row)
        source: one of INTERNAL_JSON, CSV, PDL, SEC, APOLLO, ZOOMINFO

    Returns:
        dict with keys matching companies table columns
    """
    source = source.upper()
    fn = _COMPANY_NORMALIZERS.get(source)
    if not fn:
        raise ValueError(f"Unknown source '{source}'. "
                         f"Supported: {list(_COMPANY_NORMALIZERS.keys())}")
    return fn(raw)


def normalize_person(raw: dict, source: str) -> dict:
    """
    Normalize a raw person record into our unified schema.

    Args:
        raw:    raw dict from the source (API response or CSV row)
        source: one of INTERNAL_JSON, CSV, PDL, SEC, APOLLO, ZOOMINFO

    Returns:
        dict with keys matching people table columns
    """
    source = source.upper()
    fn = _PERSON_NORMALIZERS.get(source)
    if not fn:
        raise ValueError(f"Unknown source '{source}'. "
                         f"Supported: {list(_PERSON_NORMALIZERS.keys())}")
    return fn(raw)


def supported_sources():
    """Return list of supported source names."""
    return list(_COMPANY_NORMALIZERS.keys())


# ─────────────────────────────────────────────────────────────────────────────
# Quick self-test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    # Test INTERNAL_JSON company
    sample_company = {
        "company_id": "us_b29271db-d5ed-5b7d-9204-207d744977b1",
        "legal_name": "MICROSOFT",
        "trade_name": "Microsoft",
        "domain": "microsoft.com",
        "website": "https://microsoft.com",
        "industry": "computer software",
        "naics_code": "541511",
        "address": {"city": "redmond", "state": "washington", "state_code": "WA"},
        "data_quality_score": 95
    }
    c = normalize_company(sample_company, 'INTERNAL_JSON')
    print(f"✅ Company normalized: {c['name']} | domain={c['domain']} | source={c['api_source']}")

    # Test INTERNAL_JSON person
    sample_person = {
        "person_id": "per_abc123",
        "company_id": "us_b29271db",
        "identity": {"first_name": "John", "last_name": "Doe", "full_name": "John Doe",
                     "linkedin_url": "https://linkedin.com/in/johndoe"},
        "employment": {"official_filing_title": "CEO", "standardized_title": "CEO",
                       "seniority_level": "C_SUITE", "department": "EXECUTIVE", "is_current": True},
        "tenure_and_history": {"joined_date": "2020-01-01", "years_at_company": 6.0,
                                "appointment_source": "SEC_8K", "career_history": []},
        "contact": {"work_email": "john.doe@microsoft.com", "email_pattern": "{first}.{last}@{domain}",
                    "email_verification": {"status": "VERIFIED", "total_confidence_score": 95},
                    "direct_phone": {"phone_number": "+1234567890", "phone_type": "DIRECT_DESK"}},
        "metadata": {"source_registry": "SEC",
                     "compliance_flags": {"is_business_contact": True, "opt_out_requested": False}}
    }
    p = normalize_person(sample_person, 'INTERNAL_JSON')
    print(f"✅ Person normalized: {p['full_name']} | email={p['email']} | source={p['api_source']}")

    # Test CSV person
    csv_row = {
        "company_name": "GRUPO INDUSTRIAL S.A.", "company_domain": "grupoindustrial.com",
        "full_name": "Carlos García", "standardized_title": "CEO", "seniority_level": "C_SUITE",
        "department": "EXECUTIVE", "work_email": "cgarcia@grupoindustrial.com",
        "email_status": "VERIFIED", "email_confidence_score": "85",
        "direct_phone": "+521234567890", "industry": "Manufacturing"
    }
    p2 = normalize_person(csv_row, 'CSV')
    print(f"✅ CSV person normalized: {p2['full_name']} | email={p2['email']} | source={p2['api_source']}")

    print(f"\n✅ Supported sources: {supported_sources()}")
