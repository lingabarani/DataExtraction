"use client";

import React, { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import {
  ProspectingMode,
  CompanyRecord,
  PeopleRecord,
  CompanySearchParams,
  PeopleSearchParams,
  prospectingApi,
} from "@/lib/prospecting-api";
import { AiSearchBar, SearchProgressStage } from "@/components/prospecting/ai-search-bar";
import { ProspectingSidebar } from "@/components/prospecting/prospecting-sidebar";
import { ResultsGrid } from "@/components/prospecting/results-grid";
import { DetailDrawer } from "@/components/prospecting/detail-drawer";
import { SearchEngineHub } from "@/components/prospecting/search-engine-hub";
import { synthesizeSearchQuery } from "@/lib/query-synthesizer";

export function ProspectingWorkspace() {
  const [mode, setMode] = useState<ProspectingMode>("company");
  const [hasSearched, setHasSearched] = useState(true);

  // Filter States
  const [companyFilters, setCompanyFilters] = useState<CompanySearchParams>({
    limit: 25,
    offset: 0,
    sort_by: "recent",
    sort_order: "desc",
  });

  const [peopleFilters, setPeopleFilters] = useState<PeopleSearchParams>({
    limit: 25,
    offset: 0,
    sort_by: "recent",
    sort_order: "desc",
  });

  // Results & Loading States
  const [companies, setCompanies] = useState<CompanyRecord[]>([]);
  const [people, setPeople] = useState<PeopleRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [facets, setFacets] = useState<Record<string, any>>({});
  const [isLoading, setIsLoading] = useState(false);
  const [isAiParsing, setIsAiParsing] = useState(false);
  const [searchStage, setSearchStage] = useState<SearchProgressStage>("idle");
  const [isPushing, setIsPushing] = useState(false);

  // Synthesized Query Calculation
  const synthesized = React.useMemo(
    () => synthesizeSearchQuery(mode, companyFilters, peopleFilters),
    [mode, companyFilters, peopleFilters]
  );

  // Copilot States
  const [aiSummary, setAiSummary] = useState<string | null>(null);
  const [expandedKeywords, setExpandedKeywords] = useState<string[]>([]);

  // Selection & Drawer States
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [selectedCompany, setSelectedCompany] = useState<CompanyRecord | null>(null);
  const [selectedPerson, setSelectedPerson] = useState<PeopleRecord | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  // Execute live search
  const executeSearch = useCallback(async () => {
    setIsLoading(true);
    setSearchStage("searching_database");
    try {
      if (mode === "company") {
        setSearchStage("applying_filters");
        const res = await prospectingApi.searchCompanies(companyFilters);
        setSearchStage("rendering");
        setCompanies(res.results || []);
        setTotal(res.total || 0);
        setFacets(res.facets || {});
      } else {
        setSearchStage("applying_filters");
        const res = await prospectingApi.searchPeople(peopleFilters);
        setSearchStage("rendering");
        setPeople(res.results || []);
        setTotal(res.total || 0);
        setFacets(res.facets || {});
      }
    } catch (err: any) {
      toast.error(err?.message || "Search query failed. Please retry.");
    } finally {
      setIsLoading(false);
      setSearchStage("idle");
    }
  }, [mode, companyFilters, peopleFilters]);

  // Initial and subsequent searches: only execute if user has searched
  useEffect(() => {
    if (hasSearched) {
      executeSearch();
    }
  }, [executeSearch, hasSearched]);

  // Clear selections when mode changes
  const handleModeChange = (newMode: ProspectingMode) => {
    setMode(newMode);
    setSelectedIds([]);
    setSelectedCompany(null);
    setSelectedPerson(null);
    setIsDrawerOpen(false);
    setExpandedKeywords([]);
    setAiSummary(null);
    setHasSearched(true);
  };

  // AI Prompt Parsing & Direct Groq Semantic Search
  const handleSearchPrompt = async (promptText: string) => {
    setHasSearched(true);
    setIsAiParsing(true);
    setIsLoading(true);
    setSearchStage("generating_query");
    try {
      const res = await prospectingApi.chatSearch({
        query: promptText,
        mode,
        limit: 25,
        offset: 0,
      });

      setSearchStage("applying_filters");
      setAiSummary(res.assistant_summary);
      setExpandedKeywords(res.applied_filters?.expanded_keywords || []);

      setSearchStage("rendering");
      if (res.mode === "company") {
        setMode("company");
        setCompanies(res.results || []);
        setTotal(res.total_count || 0);
        setFacets(res.facets || {});
        setCompanyFilters((prev) => ({
          ...prev,
          offset: 0,
          states: res.applied_filters.states?.length ? res.applied_filters.states : undefined,
          industries: res.applied_filters.expanded_keywords?.length
            ? res.applied_filters.expanded_keywords.slice(0, 5)
            : undefined,
          technologies: res.applied_filters.technologies?.length ? res.applied_filters.technologies : undefined,
        }));
      } else {
        setMode("people");
        setPeople(res.results || []);
        setTotal(res.total_count || 0);
        setFacets(res.facets || {});
        setPeopleFilters((prev) => ({
          ...prev,
          offset: 0,
          states: res.applied_filters.states?.length ? res.applied_filters.states : undefined,
          seniority_levels: res.applied_filters.seniority_tiers?.length ? res.applied_filters.seniority_tiers : undefined,
          departments: res.applied_filters.departments?.length ? res.applied_filters.departments : undefined,
          email_statuses: res.applied_filters.require_verified_email ? ["VERIFIED"] : undefined,
        }));
      }

      toast.success(`Search completed via ${res.search_engine}`);
    } catch (err: any) {
      toast.error("AI query search failed: " + (err?.message || "Unknown error"));
    } finally {
      setIsAiParsing(false);
      setIsLoading(false);
      setSearchStage("idle");
    }
  };

  const handleRemoveKeyword = (keywordToRemove: string) => {
    const nextKeywords = expandedKeywords.filter((k) => k !== keywordToRemove);
    setExpandedKeywords(nextKeywords);
    if (nextKeywords.length > 0) {
      handleSearchPrompt(nextKeywords.join(" "));
    } else {
      executeSearch();
    }
  };

  const handleApplyPreset = (filterCategory: string, value: string) => {
    setHasSearched(true);
    if (mode === "company") {
      if (filterCategory === "intent") {
        setCompanyFilters((prev) => ({ ...prev, intent_strengths: [value], offset: 0 }));
      } else if (filterCategory === "compliance") {
        setCompanyFilters((prev) => ({ ...prev, compliance_badges: [value], offset: 0 }));
      } else if (filterCategory === "states") {
        setCompanyFilters((prev) => ({ ...prev, states: [value], offset: 0 }));
      } else if (filterCategory === "headcount") {
        setCompanyFilters((prev) => ({ ...prev, headcount_ranges: [value], offset: 0 }));
      } else if (filterCategory === "technologies") {
        setCompanyFilters((prev) => ({ ...prev, technologies: [value], offset: 0 }));
      } else if (filterCategory === "industries") {
        setCompanyFilters((prev) => ({ ...prev, industries: [value], offset: 0 }));
      } else if (filterCategory === "funding") {
        setCompanyFilters((prev) => ({ ...prev, funding_stages: [value], offset: 0 }));
      }
    } else {
      if (filterCategory === "email_status") {
        setPeopleFilters((prev) => ({ ...prev, email_statuses: [value], offset: 0 }));
      } else if (filterCategory === "seniority") {
        setPeopleFilters((prev) => ({ ...prev, seniority_levels: [value], offset: 0 }));
      } else if (filterCategory === "departments") {
        setPeopleFilters((prev) => ({ ...prev, departments: [value], offset: 0 }));
      } else if (filterCategory === "phone") {
        setPeopleFilters((prev) => ({ ...prev, has_phone: true, offset: 0 }));
      } else if (filterCategory === "states") {
        setPeopleFilters((prev) => ({ ...prev, states: [value], offset: 0 }));
      }
    }
  };

  const handleDirectSearch = (queryText: string) => {
    const trimmed = queryText.trim();
    if (!trimmed) return;
    handleSearchPrompt(trimmed);
  };

  const handleCompanyFiltersChange = (newFilters: CompanySearchParams) => {
    setCompanyFilters(newFilters);
    setHasSearched(true);
  };

  const handlePeopleFiltersChange = (newFilters: PeopleSearchParams) => {
    setPeopleFilters(newFilters);
    setHasSearched(true);
  };

  const handleResetSearch = () => {
    setHasSearched(true);
    setAiSummary(null);
    setExpandedKeywords([]);
    setSelectedIds([]);
    if (mode === "company") {
      setCompanyFilters({ limit: 25, offset: 0, sort_by: "recent", sort_order: "desc" });
    } else {
      setPeopleFilters({ limit: 25, offset: 0, sort_by: "recent", sort_order: "desc" });
    }
  };

  // Compute Active Filter Pills
  const activePills = React.useMemo(() => {
    const pills: { category: string; value: string; label: string }[] = [];
    if (mode === "company") {
      if (companyFilters.query) {
        pills.push({ category: "query", value: companyFilters.query, label: `Query: ${companyFilters.query}` });
      }
      if (companyFilters.company_domain) {
        pills.push({ category: "company_domain", value: companyFilters.company_domain, label: `Domain: ${companyFilters.company_domain}` });
      }
      companyFilters.states?.forEach((st) => pills.push({ category: "states", value: st, label: `State: ${st}` }));
      companyFilters.industries?.forEach((ind) =>
        pills.push({ category: "industries", value: ind, label: `Industry: ${ind}` })
      );
      companyFilters.headcount_ranges?.forEach((hc) =>
        pills.push({ category: "headcount", value: hc, label: `Employees: ${hc}` })
      );
      companyFilters.revenue_ranges?.forEach((rev) =>
        pills.push({ category: "revenue", value: rev, label: `Revenue: ${rev}` })
      );
      companyFilters.funding_stages?.forEach((f) =>
        pills.push({ category: "funding", value: f, label: `Funding: ${f}` })
      );
      companyFilters.technologies?.forEach((t) => pills.push({ category: "technologies", value: t, label: `Tech: ${t}` }));
      companyFilters.compliance_badges?.forEach((c) =>
        pills.push({ category: "compliance", value: c, label: `Security: ${c}` })
      );
      companyFilters.intent_strengths?.forEach((is) =>
        pills.push({ category: "intent", value: is, label: `Intent: ${is}` })
      );
    } else {
      if (peopleFilters.query) {
        pills.push({ category: "query", value: peopleFilters.query, label: `Query: ${peopleFilters.query}` });
      }
      if (peopleFilters.company_domain) {
        pills.push({ category: "company_domain", value: peopleFilters.company_domain, label: `Domain: ${peopleFilters.company_domain}` });
      }
      if (peopleFilters.has_phone) {
        pills.push({ category: "has_phone", value: "true", label: "Direct Phone" });
      }
      peopleFilters.titles?.forEach((t) =>
        pills.push({ category: "titles", value: t, label: `Title: ${t}` })
      );
      peopleFilters.seniority_levels?.forEach((s) =>
        pills.push({ category: "seniority", value: s, label: `Seniority: ${s.replace("_", " ")}` })
      );
      peopleFilters.departments?.forEach((d) =>
        pills.push({ category: "department", value: d, label: `Dept: ${d.replace("_", " ")}` })
      );
      peopleFilters.states?.forEach((st) => pills.push({ category: "states", value: st, label: `State: ${st}` }));
      peopleFilters.email_statuses?.forEach((es) =>
        pills.push({ category: "email_status", value: es, label: `Email: ${es}` })
      );
      if (peopleFilters.company_name) {
        pills.push({
          category: "company_name",
          value: peopleFilters.company_name,
          label: `Company: ${peopleFilters.company_name}`,
        });
      }
    }
    return pills;
  }, [mode, companyFilters, peopleFilters]);

  const handleRemovePill = (category: string, value: string) => {
    if (mode === "company") {
      if (category === "query") {
        setCompanyFilters({ ...companyFilters, query: undefined, offset: 0 });
      } else if (category === "company_domain") {
        setCompanyFilters({ ...companyFilters, company_domain: undefined, offset: 0 });
      } else if (category === "funding") {
        setCompanyFilters({
          ...companyFilters,
          funding_stages: companyFilters.funding_stages?.filter((f) => f !== value),
          offset: 0,
        });
      } else if (category === "states") {
        setCompanyFilters({
          ...companyFilters,
          states: companyFilters.states?.filter((s) => s !== value),
          offset: 0,
        });
      } else if (category === "industries") {
        setCompanyFilters({
          ...companyFilters,
          industries: companyFilters.industries?.filter((i) => i !== value),
          offset: 0,
        });
      } else if (category === "headcount") {
        setCompanyFilters({
          ...companyFilters,
          headcount_ranges: companyFilters.headcount_ranges?.filter((h) => h !== value),
          offset: 0,
        });
      } else if (category === "revenue") {
        setCompanyFilters({
          ...companyFilters,
          revenue_ranges: companyFilters.revenue_ranges?.filter((r) => r !== value),
          offset: 0,
        });
      } else if (category === "technologies") {
        setCompanyFilters({
          ...companyFilters,
          technologies: companyFilters.technologies?.filter((t) => t !== value),
          offset: 0,
        });
      } else if (category === "compliance") {
        setCompanyFilters({
          ...companyFilters,
          compliance_badges: companyFilters.compliance_badges?.filter((b) => b !== value),
          offset: 0,
        });
      } else if (category === "intent") {
        setCompanyFilters({
          ...companyFilters,
          intent_strengths: companyFilters.intent_strengths?.filter((s) => s !== value),
          offset: 0,
        });
      }
    } else {
      if (category === "query") {
        setPeopleFilters({ ...peopleFilters, query: undefined, offset: 0 });
      } else if (category === "company_domain") {
        setPeopleFilters({ ...peopleFilters, company_domain: undefined, offset: 0 });
      } else if (category === "has_phone") {
        setPeopleFilters({ ...peopleFilters, has_phone: undefined, offset: 0 });
      } else if (category === "titles") {
        setPeopleFilters({
          ...peopleFilters,
          titles: peopleFilters.titles?.filter((t) => t !== value),
          offset: 0,
        });
      } else if (category === "seniority") {
        setPeopleFilters({
          ...peopleFilters,
          seniority_levels: peopleFilters.seniority_levels?.filter((s) => s !== value),
          offset: 0,
        });
      } else if (category === "department") {
        setPeopleFilters({
          ...peopleFilters,
          departments: peopleFilters.departments?.filter((d) => d !== value),
          offset: 0,
        });
      } else if (category === "states") {
        setPeopleFilters({
          ...peopleFilters,
          states: peopleFilters.states?.filter((s) => s !== value),
          offset: 0,
        });
      } else if (category === "email_status") {
        setPeopleFilters({
          ...peopleFilters,
          email_statuses: peopleFilters.email_statuses?.filter((e) => e !== value),
          offset: 0,
        });
      } else if (category === "company_name") {
        setPeopleFilters({ ...peopleFilters, company_name: undefined, offset: 0 });
      }
    }
  };

  const handleClearAllPills = () => {
    if (mode === "company") {
      setCompanyFilters({ limit: 25, offset: 0, sort_by: "recent", sort_order: "desc" });
    } else {
      setPeopleFilters({ limit: 25, offset: 0, sort_by: "recent", sort_order: "desc" });
    }
    setAiSummary(null);
  };

  // Selection Toggles
  const handleToggleSelectId = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]
    );
  };

  const handleSelectAllVisible = () => {
    const visibleIds =
      mode === "company" ? companies.map((c) => c.org_id) : people.map((p) => p.person_id);
    setSelectedIds(Array.from(new Set([...selectedIds, ...visibleIds])));
  };

  const handleClearSelection = () => {
    setSelectedIds([]);
  };

  // Inspect Row Handlers
  const handleInspectCompany = (comp: CompanyRecord) => {
    setSelectedCompany(comp);
    setSelectedPerson(null);
    setIsDrawerOpen(true);
  };

  const handleInspectPerson = (pers: PeopleRecord) => {
    setSelectedPerson(pers);
    setSelectedCompany(null);
    setIsDrawerOpen(true);
  };

  // Outbound OneReach Webhook Handlers
  const handlePushToOneReach = async (type: "company" | "person", id: string) => {
    setIsPushing(true);
    try {
      const res = await prospectingApi.pushToOneReach(type, [id]);
      toast.success(`Successfully dispatched to OneReach. Delivery ID: ${res.delivery_id.slice(0, 8)}`);
    } catch (err: any) {
      toast.error("OneReach dispatch failed: " + (err?.message || "Internal error"));
    } finally {
      setIsPushing(false);
    }
  };

  const handlePushToOneReachBatch = async () => {
    if (selectedIds.length === 0) return;
    setIsPushing(true);
    try {
      const entityType = mode === "company" ? "company" : "person";
      const res = await prospectingApi.pushToOneReach(entityType, selectedIds);
      toast.success(
        `Dispatched batch of ${res.record_count} ${mode} records to OneReach! Signed with HMAC-SHA256.`
      );
      setSelectedIds([]);
    } catch (err: any) {
      toast.error("Batch delivery failed: " + (err?.message || "Internal error"));
    } finally {
      setIsPushing(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Layer 1: Unified AI Prospecting Search Bar */}
      <AiSearchBar
        mode={mode}
        onModeChange={handleModeChange}
        onSearchPrompt={handleSearchPrompt}
        isLoading={isLoading || isAiParsing}
        searchStage={searchStage}
        synthesizedQuery={synthesized.rawQueryString}
        aiSummary={aiSummary}
        onClearSummary={() => setAiSummary(null)}
        expandedKeywords={expandedKeywords}
        onRemoveKeyword={handleRemoveKeyword}
        activePills={activePills}
        onRemovePill={handleRemovePill}
        onClearAllPills={handleClearAllPills}
      />

      {/* Main Workspace Layout: Sidebar + (Hub or ResultsGrid) */}
      <div className="flex flex-col md:flex-row gap-4 items-start">
        {/* Layer 2: Faceted Filter Sidebar */}
        <ProspectingSidebar
          mode={mode}
          companyFilters={companyFilters}
          onCompanyFiltersChange={handleCompanyFiltersChange}
          peopleFilters={peopleFilters}
          onPeopleFiltersChange={handlePeopleFiltersChange}
          facets={facets}
          onResetFilters={handleResetSearch}
        />

        {/* Live Results Grid */}
        <ResultsGrid
          mode={mode}
          companies={companies}
          people={people}
          total={total}
          limit={mode === "company" ? companyFilters.limit || 25 : peopleFilters.limit || 25}
          offset={mode === "company" ? companyFilters.offset || 0 : peopleFilters.offset || 0}
          currentSort={mode === "company" ? (companyFilters.sort_by || "recent") : (peopleFilters.sort_by || "recent")}
          onSortChange={(newSort) => {
            if (mode === "company") {
              setCompanyFilters({ ...companyFilters, sort_by: newSort, offset: 0 });
            } else {
              setPeopleFilters({ ...peopleFilters, sort_by: newSort, offset: 0 });
            }
          }}
          isLoading={isLoading}
          selectedIds={selectedIds}
          onToggleSelectId={handleToggleSelectId}
          onSelectAllVisible={handleSelectAllVisible}
          onClearSelection={handleClearSelection}
          onPageChange={(newOffset) => {
            if (mode === "company") setCompanyFilters({ ...companyFilters, offset: newOffset });
            else setPeopleFilters({ ...peopleFilters, offset: newOffset });
          }}
          onInspectCompany={handleInspectCompany}
          onInspectPerson={handleInspectPerson}
          onPushToOneReachBatch={handlePushToOneReachBatch}
          isPushing={isPushing}
          onResetSearch={handleResetSearch}
        />
      </div>

      {/* Layer 4: Enriched Slide-Over Detail Drawer */}
      <DetailDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        company={selectedCompany}
        person={selectedPerson}
        onPushToOneReach={handlePushToOneReach}
        isPushing={isPushing}
      />
    </div>
  );
}
