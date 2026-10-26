"use client";
import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";

// ── JSONB sub-types matching PostgreSQL us_leads / mexico_leads columns ────────

export interface ContactJSON {
  email:                  string | null;
  email_status:           "DELIVERABLE" | "MX_CONFIRMED" | "SYNTAX_VALID" | "RISKY" | "UNDELIVERABLE" | "VERIFIED" | "VALID" | "GUESSED" | "INVALID" | "MISSING" | null;
  email_evidence_level?:  string | null;
  email_confidence_score: number | null;
  email_checks?: {
    syntax:       boolean;
    domain:       boolean;
    registered_domain?: string | null;
    mx_record:    boolean;
    disposable:   boolean;
    role_addr:    boolean;
    pre_verified: boolean;
    smtp_verified?: boolean;
  };
  phone:         string | null;
  phone_national?: string | null;
  phone_status:  "VALID_E164" | "NORMALIZED" | "INVALID" | "MISSING" | null;
  phone_country: string | null;
  phone_type?:   string | null;
  phone_raw:     string | null;
  linkedin_url:  string | null;
  validated_at:  string | null;
}

export interface PersonJSON {
  id?:                  string;
  full_name:            string | null;
  first_name:           string | null;
  middle_name?:         string | null;
  last_name:            string | null;
  title:                string | null;
  standardized_title:   string | null;
  official_title?:      string | null;
  seniority_level:      string | null;
  department:           string | null;
  is_current:           boolean;
  joined_date?:         string | null;
  years_at_company?:    number | null;
  appointment_source?:  string | null;
  source_document_url?: string | null;
  career_history?:      Array<{
    company_name: string;
    role:         string;
    start_date:   string | null;
    end_date:     string | null;
    is_current:   boolean;
  }>;
  linkedin_url?:        string | null;
  is_business_contact?: boolean;
  opt_out_requested?:   boolean;
  source_registry?:     string | null;
  data_quality_score?:  number | null;
  api_source?:          string | null;
}

export interface CompanyJSON {
  id?:             string | null;
  name:            string | null;
  legal_name?:     string | null;
  trade_name?:     string | null;
  website?:        string | null;
  domain?:         string | null;
  email?:          string | null;
  phone?:          string | null;
  phones?:         unknown[];
  emails?:         unknown[];
  industry?:       string | null;
  naics_code?:     string | null;
  sic_code?:       string | null;
  ein?:            string | null;
  cik?:            string | null;
  rfc?:            string | null;
  rfc_type?:       string | null;
  employee_min?:   number | null;
  employee_max?:   number | null;
  employee_band?:  string | null;
  address?: {
    street?:      string | null;
    number?:      string | null;
    colony?:      string | null;
    city?:        string | null;
    municipality?:string | null;
    state?:       string | null;
    state_code?:  string | null;
    zip_code?:    string | null;
    county?:      string | null;
    country?:     string | null;
  };
  latitude?:            number | null;
  longitude?:           number | null;
  data_quality_score?:  number | null;
  last_verified_at?:    string | null;
  source_count?:        number | null;
}

// ── Main Lead type — mirrors us_leads + mexico_leads flat columns ─────────────

export interface Lead {
  id:                     string;
  // Person flat
  full_name:              string | null;
  first_name:             string | null;
  last_name:              string | null;
  title:                  string | null;
  standardized_title:     string | null;
  seniority_level:        string | null;
  department:             string | null;
  email:                  string | null;
  email_status:           string | null;
  email_confidence_score: number | null;
  phone:                  string | null;
  linkedin_url:           string | null;
  is_current:             boolean;
  // Company flat
  company_id:             string | null;
  company_name:           string | null;
  domain:                 string | null;
  industry:               string | null;
  naics_code:             string | null;
  ein:                    string | null;
  cik:                    string | null;
  employee_band:          string | null;
  city:                   string | null;
  state:                  string | null;
  state_code:             string | null;
  zip_code:               string | null;
  country:                string;
  // Quality
  person_quality_score:   number | null;
  company_quality_score:  number | null;
  lead_score:             number | null;
  api_source:             string | null;
  // JSONB
  person:                 PersonJSON  | null;
  company:                CompanyJSON | null;
  contact:                ContactJSON | null;
  // Timestamps
  created_at:             string;
  updated_at:             string;
  // UI helpers (computed on backend)
  table:                  "us_leads" | "mexico_leads";
}

export interface PaginatedLeads {
  data:  Lead[];
  total: number;
  page:  number;
  limit: number;
}

export interface LeadFilter {
  table?:          "us_leads" | "mexico_leads";
  q?:              string;         // natural-language or keyword
  nl_query?:       string;         // full AI natural-language query
  campaignId?:     string;         // campaign ID filter
  seniority?:      string;
  industry?:       string;
  state_code?:     string;
  email_status?:   string;
  api_source?:     string;
  country?:        string;
  min_score?:      number;
  page?:           number;
  limit?:          number;
}

// ── Hooks ─────────────────────────────────────────────────────────────────────

export function useLeads(filter: LeadFilter = {}) {
  const [leads,   setLeads]   = useState<Lead[]>([]);
  const [total,   setTotal]   = useState(0);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);

  const {
    table = "us_leads", q, nl_query, seniority, industry,
    state_code, email_status, api_source, country,
    min_score, page = 1, limit = 50,
  } = filter;

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("table",  table);
      params.set("page",   String(page));
      params.set("limit",  String(limit));
      if (q)            params.set("q",            q);
      if (nl_query)     params.set("nl_query",     nl_query);
      if (seniority)    params.set("seniority",    seniority);
      if (industry)     params.set("industry",     industry);
      if (state_code)   params.set("state_code",   state_code);
      if (email_status) params.set("email_status", email_status);
      if (api_source)   params.set("api_source",   api_source);
      if (country)      params.set("country",      country);
      if (min_score)    params.set("min_score",     String(min_score));

      const result = await api.get<PaginatedLeads>(`/leads?${params}`);
      setLeads(result.data);
      setTotal(result.total);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [table, q, nl_query, seniority, industry, state_code,
      email_status, api_source, country, min_score, page, limit]);

  useEffect(() => { refresh(); }, [refresh]);
  return { leads, total, loading, error, refresh };
}

export function useLead(id: string, table: "us_leads" | "mexico_leads" = "us_leads") {
  const [lead,    setLead]    = useState<Lead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get<Lead>(`/leads/${id}?table=${table}`);
      setLead(data);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [id, table]);

  useEffect(() => { refresh(); }, [refresh]);
  return { lead, loading, error, refresh };
}

// ── DB Stats hook ─────────────────────────────────────────────────────────────

export interface DbStats {
  us_total:           number;
  mx_total:           number;
  us_with_phone:      number;
  us_with_email:      number;
  us_verified_email:  number;
  mx_with_phone:      number;
  mx_with_email:      number;
  mx_verified_email:  number;
  by_source:          Array<{ source: string; count: number; avg_score: number }>;
  by_industry:        Array<{ industry: string; count: number }>;
  by_seniority:       Array<{ seniority: string; count: number }>;
  by_state:           Array<{ state_code: string; count: number }>;
}

export function useDbStats() {
  const [stats,   setStats]   = useState<DbStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);

  useEffect(() => {
    api.get<DbStats>("/stats")
      .then(setStats)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  return { stats, loading, error };
}
