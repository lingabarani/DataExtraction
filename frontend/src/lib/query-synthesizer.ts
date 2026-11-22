/**
 * DataExtraction — Enterprise Search Query Synthesizer
 * ======================================================
 * Synthesizes transparent Apollo.io / OneReach-style structured queries
 * from active multi-faceted filters for Company & People modes.
 */

import { CompanySearchParams, PeopleSearchParams, ProspectingMode } from "@/lib/prospecting-api";

export interface SynthesizedQuery {
  rawQueryString: string;
  hasFilters: boolean;
  filterChipsCount: number;
}

export function synthesizeSearchQuery(
  mode: ProspectingMode,
  companyFilters: CompanySearchParams,
  peopleFilters: PeopleSearchParams
): SynthesizedQuery {
  const parts: string[] = [];

  if (mode === "company") {
    if (companyFilters.query?.trim()) {
      parts.push(`keywords:"${companyFilters.query.trim()}"`);
    }
    if (companyFilters.company_domain?.trim()) {
      parts.push(`domain:"${companyFilters.company_domain.trim()}"`);
    }
    if (companyFilters.states && companyFilters.states.length > 0) {
      const stateList = companyFilters.states.map((s) => `"${s}"`).join(" OR ");
      parts.push(`location:(${stateList})`);
    }
    if (companyFilters.industries && companyFilters.industries.length > 0) {
      const indList = companyFilters.industries.map((i) => `"${i}"`).join(" OR ");
      parts.push(`industry:(${indList})`);
    }
    if (companyFilters.headcount_ranges && companyFilters.headcount_ranges.length > 0) {
      const hcList = companyFilters.headcount_ranges.map((h) => `"${h}"`).join(" OR ");
      parts.push(`employees:(${hcList})`);
    }
    if (companyFilters.revenue_ranges && companyFilters.revenue_ranges.length > 0) {
      const revList = companyFilters.revenue_ranges.map((r) => `"${r}"`).join(" OR ");
      parts.push(`revenue:(${revList})`);
    }
    if (companyFilters.technologies && companyFilters.technologies.length > 0) {
      const techList = companyFilters.technologies.map((t) => `"${t}"`).join(" OR ");
      parts.push(`tech:(${techList})`);
    }
    if (companyFilters.intent_strengths && companyFilters.intent_strengths.length > 0) {
      parts.push(`intent:(${companyFilters.intent_strengths.join(" OR ")})`);
    }
    if (companyFilters.compliance_badges && companyFilters.compliance_badges.length > 0) {
      parts.push(`compliance:(${companyFilters.compliance_badges.join(" OR ")})`);
    }
    if (companyFilters.funding_stages && companyFilters.funding_stages.length > 0) {
      parts.push(`funding:(${companyFilters.funding_stages.join(" OR ")})`);
    }
    if (companyFilters.min_trust_score) {
      parts.push(`trust:>=${companyFilters.min_trust_score}%`);
    }
  } else {
    if (peopleFilters.query?.trim()) {
      parts.push(`keywords:"${peopleFilters.query.trim()}"`);
    }
    if (peopleFilters.titles && peopleFilters.titles.length > 0) {
      const titleList = peopleFilters.titles.map((t) => `"${t}"`).join(" OR ");
      parts.push(`title:(${titleList})`);
    }
    if (peopleFilters.seniority_levels && peopleFilters.seniority_levels.length > 0) {
      const senList = peopleFilters.seniority_levels.map((s) => `"${s.replace("_", " ")}"`).join(" OR ");
      parts.push(`seniority:(${senList})`);
    }
    if (peopleFilters.departments && peopleFilters.departments.length > 0) {
      const deptList = peopleFilters.departments.map((d) => `"${d.replace("_", " ")}"`).join(" OR ");
      parts.push(`department:(${deptList})`);
    }
    if (peopleFilters.states && peopleFilters.states.length > 0) {
      const stateList = peopleFilters.states.map((s) => `"${s}"`).join(" OR ");
      parts.push(`location:(${stateList})`);
    }
    if (peopleFilters.email_statuses && peopleFilters.email_statuses.length > 0) {
      parts.push(`email:(${peopleFilters.email_statuses.join(" OR ")})`);
    }
    if (peopleFilters.has_phone) {
      parts.push(`phone:verified`);
    }
    if (peopleFilters.company_name?.trim()) {
      parts.push(`company:"${peopleFilters.company_name.trim()}"`);
    }
    if (peopleFilters.company_domain?.trim()) {
      parts.push(`domain:"${peopleFilters.company_domain.trim()}"`);
    }
    if (peopleFilters.min_deliverability_score) {
      parts.push(`deliverability:>=${peopleFilters.min_deliverability_score}%`);
    }
  }

  const rawQueryString = parts.length > 0 ? parts.join(" AND ") : "";

  return {
    rawQueryString,
    hasFilters: parts.length > 0,
    filterChipsCount: parts.length,
  };
}
