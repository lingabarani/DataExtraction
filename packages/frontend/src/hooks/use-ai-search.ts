"use client";
import { useState, useCallback } from "react";
import { api } from "@/lib/api";
import type { Lead, LeadFilter } from "@/hooks/use-leads";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ParsedQuery {
  filters:        LeadFilter;
  sql_where:      string;
  explanation:    string;
  confidence:     number;   // 0–100
  suggestions:    string[];
}

export interface AISearchResult {
  query:          string;
  parsed:         ParsedQuery;
  leads:          Lead[];
  total:          number;
  duration_ms:    number;
}

// ── Intent keyword parser (client-side, no API call needed) ───────────────────
// Used as fallback when backend AI endpoint is unavailable.

const SENIORITY_MAP: Record<string, string> = {
  ceo:       "C_SUITE", cfo: "C_SUITE", coo: "C_SUITE", cto: "C_SUITE",
  "c-suite": "C_SUITE", "c suite": "C_SUITE", "csuite": "C_SUITE",
  vp:        "VP", "vice president": "VP",
  director:  "DIRECTOR",
  manager:   "MANAGER",
  founder:   "FOUNDER", owner: "OWNER",
};

const INDUSTRY_MAP: Record<string, string> = {
  healthcare:    "Healthcare",      health:        "Healthcare",
  tech:          "Computer Software", technology:  "Computer Software", software: "Computer Software",
  banking:       "Banking and Finance", finance:   "Banking and Finance", bank: "Banking and Finance",
  nonprofit:     "Nonprofits and Associations", nonprofits: "Nonprofits and Associations",
  manufacturing: "Industrial Manufacturing & Transformation",
  contractor:    "Federal Contractor", federal: "Federal Contractor",
  energy:        "Energy", pharmaceutical: "Healthcare",
  education:     "Education", school: "Education",
  retail:        "Retail",
};

const STATE_MAP: Record<string, string> = {
  california: "CA", texas: "TX", "new york": "NY", florida: "FL",
  illinois:   "IL", pennsylvania: "PA", ohio: "OH", georgia: "GA",
  washington: "WA", arizona: "AZ", massachusetts: "MA", michigan: "MI",
  colorado:   "CO", "north carolina": "NC", virginia: "VA",
};

function parseQueryClient(query: string): Partial<LeadFilter> & { explanation: string } {
  const q    = query.toLowerCase();
  const out: Partial<LeadFilter> = {};
  const parts: string[] = [];

  // Seniority
  for (const [kw, val] of Object.entries(SENIORITY_MAP)) {
    if (q.includes(kw)) { out.seniority = val; parts.push(val.replace("_","-")); break; }
  }

  // Industry
  for (const [kw, val] of Object.entries(INDUSTRY_MAP)) {
    if (q.includes(kw)) { out.industry = val; parts.push(val); break; }
  }

  // State
  for (const [kw, val] of Object.entries(STATE_MAP)) {
    if (q.includes(kw)) { out.state_code = val; parts.push(val); break; }
  }

  // Email
  if (q.includes("verified email") || q.includes("valid email"))
    { out.email_status = "VERIFIED"; parts.push("verified email"); }

  // Table
  if (q.includes("mexico") || q.includes("mx"))
    { out.table = "mexico_leads"; }
  else
    { out.table = "us_leads"; }

  const explanation = parts.length
    ? `Filtering by ${parts.join(", ")}`
    : "Showing all leads";

  return { ...out, explanation };
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useAISearch() {
  const [result,   setResult]   = useState<AISearchResult | null>(null);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState<string | null>(null);
  const [history,  setHistory]  = useState<string[]>([]);

  const search = useCallback(async (query: string) => {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    const t0 = Date.now();

    try {
      // Try backend AI endpoint first
      const res = await api.post<AISearchResult>("/ai/search", { query });
      setResult(res);
      setHistory(h => [query, ...h.filter(q => q !== query)].slice(0, 10));
    } catch {
      // Fallback: client-side keyword parsing → useLeads call
      const { explanation, ...filters } = parseQueryClient(query);
      const params = new URLSearchParams();
      params.set("table", filters.table ?? "us_leads");
      params.set("limit", "50");
      if (filters.seniority)    params.set("seniority",    filters.seniority);
      if (filters.industry)     params.set("industry",     filters.industry);
      if (filters.state_code)   params.set("state_code",   filters.state_code);
      if (filters.email_status) params.set("email_status", filters.email_status);

      try {
        const fallback = await api.get<{ data: Lead[]; total: number }>(`/leads?${params}`);
        setResult({
          query,
          parsed: {
            filters,
            sql_where:   "",
            explanation,
            confidence:  70,
            suggestions: [],
          },
          leads:       fallback.data,
          total:       fallback.total,
          duration_ms: Date.now() - t0,
        });
        setHistory(h => [query, ...h.filter(q => q !== query)].slice(0, 10));
      } catch (e2) {
        setError(String(e2));
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const clear = useCallback(() => {
    setResult(null);
    setError(null);
  }, []);

  return { result, loading, error, history, search, clear };
}
