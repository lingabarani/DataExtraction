"use client";

import React, { useEffect, useState, useCallback, useRef } from "react";
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
import { StickyFilterBar } from "@/components/prospecting/sticky-filter-bar";
import { RowPreviewPanel } from "@/components/prospecting/row-preview-panel";
import { ResultsGrid } from "@/components/prospecting/results-grid";
import { DetailDrawer } from "@/components/prospecting/detail-drawer";
import { synthesizeSearchQuery } from "@/lib/query-synthesizer";
import { normalizePercentScore, formatRevenueBadge, formatEmployeeBadge } from "@/lib/formatters";

export function ProspectingWorkspace() {
  const [mode, setMode] = useState<ProspectingMode>("company");
  const [hasSearched, setHasSearched] = useState(true);
  const skipNextExecuteSearchRef = useRef(false);
  const initialUrlHandledRef = useRef(false);

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
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [isAiParsing, setIsAiParsing] = useState(false);
  const [searchStage, setSearchStage] = useState<SearchProgressStage>("idle");
  const [isPushing, setIsPushing] = useState(false);

  const synthesized = React.useMemo(
    () => synthesizeSearchQuery(mode, companyFilters, peopleFilters),
    [mode, companyFilters, peopleFilters]
  );

  // Copilot States
  const [aiSummary, setAiSummary] = useState<string | null>(null);
  const [expandedKeywords, setExpandedKeywords] = useState<string[]>([]);

  // Selection, Preview & Drawer States
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [previewCompany, setPreviewCompany] = useState<CompanyRecord | null>(null);
  const [previewPerson, setPreviewPerson] = useState<PeopleRecord | null>(null);
  const [selectedCompany, setSelectedCompany] = useState<CompanyRecord | null>(null);
  const [selectedPerson, setSelectedPerson] = useState<PeopleRecord | null>(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  // Execute live search (reset or append depending on offset)
  const executeSearch = useCallback(async () => {
    const currentOffset =
      mode === "company" ? companyFilters.offset || 0 : peopleFilters.offset || 0;
    const isAppend = currentOffset > 0;

    if (isAppend) {
      setIsLoadingMore(true);
    } else {
      setIsLoading(true);
      setSearchStage("searching_database");
    }

    try {
      if (mode === "company") {
        if (!isAppend) setSearchStage("applying_filters");
        const res = await prospectingApi.searchCompanies(companyFilters);
        if (!isAppend) setSearchStage("rendering");
        setCompanies((prev) =>
          isAppend ? [...prev, ...(res.results || [])] : res.results || []
        );
        setTotal(res.total || 0);
        setFacets(res.facets || {});
      } else {
        if (!isAppend) setSearchStage("applying_filters");
        const res = await prospectingApi.searchPeople(peopleFilters);
        if (!isAppend) setSearchStage("rendering");
        setPeople((prev) =>
          isAppend ? [...prev, ...(res.results || [])] : res.results || []
        );
        setTotal(res.total || 0);
        setFacets(res.facets || {});
      }
    } catch (err: any) {
      toast.error(err?.message || "Search query failed. Please retry.");
    } finally {
      setIsLoading(false);
      setIsLoadingMore(false);
      setSearchStage("idle");
    }
  }, [mode, companyFilters, peopleFilters]);

  // AI Prompt Parsing & Direct Groq Semantic Search
  const handleSearchPrompt = useCallback(
    async (promptText: string) => {
      setHasSearched(true);
      setIsAiParsing(true);
      setIsLoading(true);
      setPreviewCompany(null);
      setPreviewPerson(null);
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
        skipNextExecuteSearchRef.current = true;
        if (res.mode === "company") {
          setMode("company");
          setCompanies(res.results || []);
          setTotal(res.total_count || 0);
          setFacets(res.facets || {});
          const derivedIndustries = res.applied_filters.expanded_keywords?.length
            ? res.applied_filters.expanded_keywords.slice(0, 5)
            : undefined;

          const isShortNameQuery =
            promptText.trim().split(/\s+/).length <= 2 &&
            !promptText.toLowerCase().includes(" in ") &&
            !promptText.toLowerCase().includes(" near ");
          const effectiveQuery = isShortNameQuery ? promptText.trim() : undefined;

          setCompanyFilters((prev) => ({
            ...prev,
            query: effectiveQuery,
            offset: 0,
            states: res.applied_filters.states?.length ? res.applied_filters.states : undefined,
            industries: derivedIndustries?.length ? derivedIndustries : undefined,
            technologies: res.applied_filters.technologies?.length
              ? res.applied_filters.technologies
              : undefined,
          }));
        } else {
          const isShortNameQuery =
            promptText.trim().split(/\s+/).length <= 2 &&
            !promptText.toLowerCase().includes(" in ") &&
            !promptText.toLowerCase().includes(" near ");
          const effectiveQuery = isShortNameQuery ? promptText.trim() : undefined;

          setMode("people");
          setPeople(res.results || []);
          setTotal(res.total_count || 0);
          setFacets(res.facets || {});
          setPeopleFilters((prev) => ({
            ...prev,
            query: effectiveQuery,
            offset: 0,
            states: res.applied_filters.states?.length ? res.applied_filters.states : undefined,
            seniority_levels: res.applied_filters.seniority_tiers?.length
              ? res.applied_filters.seniority_tiers
              : undefined,
            departments: res.applied_filters.departments?.length
              ? res.applied_filters.departments
              : undefined,
            email_statuses: res.applied_filters.require_verified_email ? ["VERIFIED"] : undefined,
            has_phone: res.applied_filters.require_direct_phone ? true : undefined,
          }));
        }

        toast.success("AI Intelligence Search complete");

        if (typeof window !== "undefined") {
          const url = new URL(window.location.href);
          url.searchParams.set("q", promptText);
          if (res.applied_filters.states?.length) {
            url.searchParams.set("states", res.applied_filters.states.join(","));
          } else {
            url.searchParams.delete("states");
          }
          window.history.replaceState({}, "", url.toString());
        }
      } catch (err: any) {
        toast.error("AI query search failed: " + (err?.message || "Unknown error"));
      } finally {
        setIsAiParsing(false);
        setIsLoading(false);
        setSearchStage("idle");
      }
    },
    [mode]
  );

  useEffect(() => {
    void Promise.resolve().then(() => {
      if (!initialUrlHandledRef.current && typeof window !== "undefined") {
        initialUrlHandledRef.current = true;
        const params = new URLSearchParams(window.location.search);
        const urlQ = params.get("q");
        if (urlQ) {
          void handleSearchPrompt(urlQ);
          return;
        }
      }
      if (skipNextExecuteSearchRef.current) {
        skipNextExecuteSearchRef.current = false;
        return;
      }
      if (hasSearched) {
        void executeSearch();
      }
    });
  }, [executeSearch, handleSearchPrompt, hasSearched]);

  const handleModeChange = (newMode: ProspectingMode) => {
    setMode(newMode);
    setSelectedIds([]);
    setPreviewCompany(null);
    setPreviewPerson(null);
    setSelectedCompany(null);
    setSelectedPerson(null);
    setIsDrawerOpen(false);
    setExpandedKeywords([]);
    setAiSummary(null);
    setHasSearched(true);
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

  const handleCompanyFiltersChange = (newFilters: CompanySearchParams) => {
    setCompanyFilters({ ...newFilters, offset: 0 });
    setHasSearched(true);
  };

  const handlePeopleFiltersChange = (newFilters: PeopleSearchParams) => {
    setPeopleFilters({ ...newFilters, offset: 0 });
    setHasSearched(true);
  };

  const handleResetSearch = () => {
    setHasSearched(true);
    setAiSummary(null);
    setExpandedKeywords([]);
    setSelectedIds([]);
    setPreviewCompany(null);
    setPreviewPerson(null);
    if (mode === "company") {
      setCompanyFilters({ limit: 25, offset: 0, sort_by: "recent", sort_order: "desc" });
    } else {
      setPeopleFilters({ limit: 25, offset: 0, sort_by: "recent", sort_order: "desc" });
    }
  };

  const handleLoadMore = () => {
    if (isLoading || isLoadingMore) return;
    if (mode === "company") {
      const nextOffset = companies.length;
      if (nextOffset < total) {
        setCompanyFilters((prev) => ({ ...prev, offset: nextOffset }));
      }
    } else {
      const nextOffset = people.length;
      if (nextOffset < total) {
        setPeopleFilters((prev) => ({ ...prev, offset: nextOffset }));
      }
    }
  };

  const activePills = React.useMemo(() => {
    const pills: { category: string; value: string; label: string }[] = [];
    if (mode === "company") {
      if (companyFilters.query) pills.push({ category: "query", value: companyFilters.query, label: `Query: ${companyFilters.query}` });
      companyFilters.states?.forEach((st) => pills.push({ category: "states", value: st, label: `State: ${st}` }));
      companyFilters.industries?.forEach((ind) => pills.push({ category: "industries", value: ind, label: `Industry: ${ind}` }));
      companyFilters.headcount_ranges?.forEach((hc) => pills.push({ category: "headcount", value: hc, label: `Employees: ${hc}` }));
      companyFilters.revenue_ranges?.forEach((rev) => pills.push({ category: "revenue", value: rev, label: `Revenue: ${rev}` }));
      if (companyFilters.min_trust_score !== undefined) {
        pills.push({ category: "min_trust_score", value: String(companyFilters.min_trust_score), label: `Trust >= ${companyFilters.min_trust_score}%` });
      }
      companyFilters.technologies?.forEach((t) => pills.push({ category: "technologies", value: t, label: `Tech: ${t}` }));
    } else {
      if (peopleFilters.query) pills.push({ category: "query", value: peopleFilters.query, label: `Query: ${peopleFilters.query}` });
      peopleFilters.titles?.forEach((t) => pills.push({ category: "titles", value: t, label: `Title: ${t}` }));
      peopleFilters.seniority_levels?.forEach((s) => pills.push({ category: "seniority", value: s, label: `Seniority: ${s.replace("_", " ")}` }));
      peopleFilters.departments?.forEach((d) => pills.push({ category: "department", value: d, label: `Dept: ${d.replace("_", " ")}` }));
      peopleFilters.states?.forEach((st) => pills.push({ category: "states", value: st, label: `State: ${st}` }));
    }
    return pills;
  }, [mode, companyFilters, peopleFilters]);

  const handleRemovePill = (category: string, value: string) => {
    if (mode === "company") {
      if (category === "query") setCompanyFilters({ ...companyFilters, query: undefined, offset: 0 });
      else if (category === "states") setCompanyFilters({ ...companyFilters, states: companyFilters.states?.filter((s) => s !== value), offset: 0 });
      else if (category === "industries") setCompanyFilters({ ...companyFilters, industries: companyFilters.industries?.filter((i) => i !== value), offset: 0 });
      else if (category === "headcount") setCompanyFilters({ ...companyFilters, headcount_ranges: companyFilters.headcount_ranges?.filter((h) => h !== value), offset: 0 });
      else if (category === "revenue") setCompanyFilters({ ...companyFilters, revenue_ranges: companyFilters.revenue_ranges?.filter((r) => r !== value), offset: 0 });
      else if (category === "min_trust_score") setCompanyFilters({ ...companyFilters, min_trust_score: undefined, offset: 0 });
      else if (category === "technologies") setCompanyFilters({ ...companyFilters, technologies: companyFilters.technologies?.filter((t) => t !== value), offset: 0 });
    } else {
      if (category === "query") setPeopleFilters({ ...peopleFilters, query: undefined, offset: 0 });
      else if (category === "titles") setPeopleFilters({ ...peopleFilters, titles: peopleFilters.titles?.filter((t) => t !== value), offset: 0 });
      else if (category === "seniority") setPeopleFilters({ ...peopleFilters, seniority_levels: peopleFilters.seniority_levels?.filter((s) => s !== value), offset: 0 });
      else if (category === "department") setPeopleFilters({ ...peopleFilters, departments: peopleFilters.departments?.filter((d) => d !== value), offset: 0 });
      else if (category === "states") setPeopleFilters({ ...peopleFilters, states: peopleFilters.states?.filter((s) => s !== value), offset: 0 });
    }
  };

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

  const handlePreviewCompany = (comp: CompanyRecord) => {
    setPreviewCompany(comp);
    setPreviewPerson(null);
  };

  const handlePreviewPerson = (pers: PeopleRecord) => {
    setPreviewPerson(pers);
    setPreviewCompany(null);
  };

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

  const handlePushToOneReach = async (type: "company" | "person", id: string) => {
    setIsPushing(true);
    try {
      const res = await prospectingApi.pushToOneReach(type, [id]);
      toast.success(`Synced to OneReach (${res.delivery_id.slice(0, 8)})`);
    } catch (err: any) {
      toast.error("OneReach sync failed: " + (err?.message || "Internal error"));
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
      toast.success(`Dispatched ${res.record_count} ${mode} records to OneReach.`);
      setSelectedIds([]);
    } catch (err: any) {
      toast.error("Batch sync failed: " + (err?.message || "Internal error"));
    } finally {
      setIsPushing(false);
    }
  };

  const handleQuickExportCsv = () => {
    const items = mode === "company" ? companies : people;
    if (!items.length) return;
    const header =
      mode === "company"
        ? "Company Name,Domain,Industry,Revenue,Employees,Trust\n"
        : "Name,Title,Company,Email,Phone\n";
    const rows =
      mode === "company"
        ? companies
            .map(
              (c) =>
                `"${c.legal_name}","${c.primary_domain || ""}","${c.industry || ""}","${formatRevenueBadge(c.annual_revenue_usd)}","${formatEmployeeBadge(c.employee_count_min, c.employee_count_max)}",${normalizePercentScore(c.trust_score, 85)}%`
            )
            .join("\n")
        : people
            .map(
              (p) =>
                `"${p.full_name}","${p.title || ""}","${p.company_name || ""}","${p.email || ""}","${p.phone || ""}"`
            )
            .join("\n");

    const blob = new Blob([header + rows], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `ai_search_${mode}_export.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const hasMore =
    mode === "company" ? companies.length < total : people.length < total;

  return (
    <div className="flex flex-col gap-6">
      {/* 32px Page Header */}
      <div className="flex flex-col gap-1">
        <h1 className="text-page-header text-foreground">AI Intelligence Search</h1>
        <p className="text-body-base text-muted-foreground">
          Query companies and decision-makers using natural language, semantic expansion, and verified firmographics.
        </p>
      </div>

      {/* Large Enterprise AI Search Bar */}
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
        onClearAllPills={handleResetSearch}
        onExportCsv={handleQuickExportCsv}
        canExport={(mode === "company" ? companies.length : people.length) > 0}
      />

      {/* Sticky Global Filters Bar */}
      <StickyFilterBar
        mode={mode}
        companyFilters={companyFilters}
        onCompanyFiltersChange={handleCompanyFiltersChange}
        peopleFilters={peopleFilters}
        onPeopleFiltersChange={handlePeopleFiltersChange}
        facets={facets}
        total={total}
        currentSort={
          mode === "company"
            ? companyFilters.sort_by || "recent"
            : peopleFilters.sort_by || "recent"
        }
        onSortChange={(newSort) => {
          if (mode === "company") {
            setCompanyFilters({ ...companyFilters, sort_by: newSort, offset: 0 });
          } else {
            setPeopleFilters({ ...peopleFilters, sort_by: newSort, offset: 0 });
          }
        }}
        onResetFilters={handleResetSearch}
      />

      {/* Row Preview Panel */}
      <RowPreviewPanel
        company={previewCompany}
        person={previewPerson}
        onOpenFullDrawer={() => {
          if (previewCompany) handleInspectCompany(previewCompany);
          else if (previewPerson) handleInspectPerson(previewPerson);
        }}
        onDismiss={() => {
          setPreviewCompany(null);
          setPreviewPerson(null);
        }}
      />

      {/* Modern Card-Table Hybrid with Infinite Scroll */}
      <ResultsGrid
        mode={mode}
        companies={companies}
        people={people}
        total={total}
        limit={mode === "company" ? companyFilters.limit || 25 : peopleFilters.limit || 25}
        offset={mode === "company" ? companyFilters.offset || 0 : peopleFilters.offset || 0}
        isLoading={isLoading}
        isLoadingMore={isLoadingMore}
        hasMore={hasMore}
        onLoadMore={handleLoadMore}
        selectedIds={selectedIds}
        onToggleSelectId={handleToggleSelectId}
        onSelectAllVisible={handleSelectAllVisible}
        onClearSelection={() => setSelectedIds([])}
        onPreviewCompany={handlePreviewCompany}
        onPreviewPerson={handlePreviewPerson}
        onInspectCompany={handleInspectCompany}
        onInspectPerson={handleInspectPerson}
        onPushToOneReachBatch={handlePushToOneReachBatch}
        isPushing={isPushing}
        onResetSearch={handleResetSearch}
      />

      {/* Right-Side Accessible Details Sheet */}
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
