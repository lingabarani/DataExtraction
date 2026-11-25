/**
 * DataExtraction — AI Prospecting & Intelligence Client
 * ======================================================
 * Typed client for interacting with the unified prospecting backend:
 *   - AI Query Parsing (Ollama Llama 3.1 8B + Fallback)
 *   - Faceted Organization Search
 *   - Decision-Maker People Search
 *   - OneReach HMAC Webhook Delivery
 *   - Executive Org Intelligence
 */

import { api } from "@/lib/api";

export type ProspectingMode = "company" | "people";

export interface ParseQueryResponse {
  mode: ProspectingMode;
  filters: Record<string, any>;
  summary: string;
  source: "ollama" | "fallback";
}

export interface CompanySearchParams {
  query?: string;
  company_domain?: string;
  states?: string[];
  cities?: string[];
  industries?: string[];
  naics_codes?: string[];
  headcount_ranges?: string[];
  revenue_ranges?: string[];
  funding_stages?: string[];
  technologies?: string[];
  compliance_badges?: string[];
  intent_strengths?: string[];
  intent_topics?: string[];
  min_trust_score?: number;
  min_rating?: number;
  recent_only?: boolean;
  has_verified_contacts?: boolean;
  limit?: number;
  offset?: number;
  sort_by?: string;
  sort_order?: "desc" | "asc";
}

export interface CompanyRecord {
  org_id: string;
  legal_name: string;
  display_name: string;
  primary_domain: string;
  industry: string;
  sub_industry?: string | null;
  primary_phone?: string | null;
  jurisdiction: string;
  city: string;
  state_code: string;
  employee_count_min?: number | null;
  employee_count_max?: number | null;
  formatted_address?: string | null;
  annual_revenue_usd: number;
  data_quality_score: number;
  trust_score: number;
  intent_score: number;
  intent_strength: string;
  technologies: string[];
  compliance_badges: string[];
  intent_topics?: string[];
  short_description?: string;
  decision_maker_count?: number;
  rating?: number | null;
  review_count?: number;
  sentiment_summary?: string | null;
  praise_highlights?: string[];
  complaint_alerts?: string[];
  updated_at?: string | null;
  last_verified_at?: string | null;
}

export interface PeopleSearchParams {
  query?: string;
  titles?: string[];
  seniority_levels?: string[];
  departments?: string[];
  states?: string[];
  cities?: string[];
  email_statuses?: string[];
  has_phone?: boolean;
  company_domain?: string;
  min_deliverability_score?: number;
  min_propensity_score?: number;
  recent_only?: boolean;
  company_name?: string;
  company_industries?: string[];
  limit?: number;
  offset?: number;
  sort_by?: string;
  sort_order?: "desc" | "asc";
}

export interface PeopleRecord {
  person_id: string;
  full_name: string;
  first_name?: string;
  last_name?: string;
  title: string;
  seniority_level: string;
  seniority?: string;
  department: string;
  city: string;
  state_code: string;
  email: string;
  email_status?: string;
  phone: string;
  linkedin_url?: string;
  deliverability_status?: string;
  deliverability_score?: number;
  is_catch_all?: boolean;
  mx_provider?: string;
  propensity_to_buy_score: number;
  propensity_score?: number;
  trust_score: number;
  company_id: string;
  company_name: string;
  company_domain: string;
  company_industry: string;
  updated_at?: string | null;
  last_verified_at?: string | null;
}

export interface FacetItem {
  value: string;
  count: number;
}

export interface CompanySearchResults {
  total: number;
  limit: number;
  offset: number;
  search_engine: string;
  results: CompanyRecord[];
  facets: {
    states?: FacetItem[];
    industries?: FacetItem[];
    technologies?: FacetItem[];
    intent_strengths?: FacetItem[];
  };
}

export interface PeopleSearchResults {
  total: number;
  limit: number;
  offset: number;
  results: PeopleRecord[];
  facets: {
    seniority_levels?: FacetItem[];
    departments?: FacetItem[];
    states?: FacetItem[];
    email_statuses?: FacetItem[];
  };
}

export interface PushOneReachResponse {
  status: string;
  delivery_id: string;
  record_count: number;
  signature: string;
  delivered_at: string;
}

export interface ChatSearchRequest {
  query: string;
  mode?: ProspectingMode;
  limit?: number;
  offset?: number;
}

export interface ChatSearchResponse {
  mode: ProspectingMode;
  assistant_summary: string;
  applied_filters: {
    expanded_keywords: string[];
    naics_codes: string[];
    states: string[];
    cities: string[];
    seniority_tiers: string[];
    departments: string[];
    target_titles: string[];
    technologies: string[];
    require_verified_email: boolean;
    require_direct_phone: boolean;
    min_headcount?: number | null;
    max_headcount?: number | null;
  };
  total_count: number;
  limit: number;
  offset: number;
  search_engine: string;
  results: any[];
  facets: Record<string, FacetItem[]>;
}

export interface DecisionMaker {
  person_id: string;
  name: string;
  title: string;
  seniority: string;
  department: string;
  email: string;
  phone: string;
  email_status: string;
  propensity_score: number;
  linkedin_url?: string;
}

export const prospectingApi = {
  async chatSearch(req: ChatSearchRequest): Promise<ChatSearchResponse> {
    return api.post<ChatSearchResponse>("/ai/chat-search", req, { timeoutMs: 30000 });
  },

  async parseSearchQuery(query: string, mode: ProspectingMode): Promise<ParseQueryResponse> {
    return api.post<ParseQueryResponse>("/ai/parse-search-query", { query, mode });
  },

  async searchCompanies(params: CompanySearchParams): Promise<CompanySearchResults> {
    return api.post<CompanySearchResults>("/search/companies", params, { timeoutMs: 35000 });
  },

  async searchPeople(params: PeopleSearchParams): Promise<PeopleSearchResults> {
    return api.post<PeopleSearchResults>("/search/people", params, { timeoutMs: 35000 });
  },

  async pushToOneReach(
    entityType: "company" | "person",
    ids: string[],
    campaignId?: string
  ): Promise<PushOneReachResponse> {
    return api.post<PushOneReachResponse>("/prospecting/push-onereach", {
      entity_type: entityType,
      ids,
      campaign_id: campaignId,
    });
  },

  async getCompanyDecisionMakers(orgId: string): Promise<{ org_id: string; decision_makers: DecisionMaker[] }> {
    return api.get<{ org_id: string; decision_makers: DecisionMaker[] }>(
      `/prospecting/company/${orgId}/decision-makers`
    );
  },
};
