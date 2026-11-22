"use client";

import React from "react";
import Link from "next/link";
import {
  Building2,
  Users,
  ExternalLink,
  Send,
  Download,
  Flame,
  ShieldCheck,
  Mail,
  Phone,
  CheckCircle2,
  AlertCircle,
  HelpCircle,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Sparkles,
  Search,
  RotateCcw,
  Star,
  ArrowUpDown,
  Clock,
} from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  ProspectingMode,
  CompanyRecord,
  PeopleRecord,
} from "@/lib/prospecting-api";
import { cn } from "@/lib/utils";

interface ResultsGridProps {
  mode: ProspectingMode;
  companies: CompanyRecord[];
  people: PeopleRecord[];
  total: number;
  limit: number;
  offset: number;
  isLoading: boolean;
  selectedIds: string[];
  currentSort?: string;
  onSortChange?: (newSort: string) => void;
  onToggleSelectId: (id: string) => void;
  onSelectAllVisible: () => void;
  onClearSelection: () => void;
  onPageChange: (newOffset: number) => void;
  onInspectCompany: (company: CompanyRecord) => void;
  onInspectPerson: (person: PeopleRecord) => void;
  onPushToOneReachBatch: () => void;
  isPushing: boolean;
  onResetSearch?: () => void;
}

export function ResultsGrid({
  mode,
  companies,
  people,
  total,
  limit,
  offset,
  isLoading,
  selectedIds,
  currentSort,
  onSortChange,
  onToggleSelectId,
  onSelectAllVisible,
  onClearSelection,
  onPageChange,
  onInspectCompany,
  onInspectPerson,
  onPushToOneReachBatch,
  isPushing,
  onResetSearch,
}: ResultsGridProps) {
  const currentItems = mode === "company" ? companies : people;
  const allVisibleSelected =
    currentItems.length > 0 &&
    currentItems.every((item) =>
      selectedIds.includes(mode === "company" ? (item as CompanyRecord).org_id : (item as PeopleRecord).person_id)
    );

  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.ceil(total / limit) || 1;

  const handleExportCsv = () => {
    if (currentItems.length === 0) return;
    const header =
      mode === "company"
        ? "Org ID,Company Name,Domain,Industry,Rating,Review Count,State,Employees Min,Employees Max,Trust Score,Intent Score,Updated At\n"
        : "Person ID,Name,Title,Company,Email,Deliverability,Seniority,Department,Updated At\n";

    const rows =
      mode === "company"
        ? (currentItems as CompanyRecord[])
            .map(
              (c) =>
                `"${c.org_id}","${c.legal_name}","${c.primary_domain}","${c.industry}",${c.rating || "N/A"},${c.review_count || 0},"${c.state_code}",${c.employee_count_min},${c.employee_count_max},${c.trust_score},${c.intent_score},"${c.updated_at || ""}"`
            )
            .join("\n")
        : (currentItems as PeopleRecord[])
            .map(
              (p) =>
                `"${p.person_id}","${p.full_name}","${p.title}","${p.company_name}","${p.email}","${p.deliverability_status}","${p.seniority_level}","${p.department}","${p.updated_at || ""}"`
            )
            .join("\n");

    const blob = new Blob([header + rows], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `prospecting_${mode}_export.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="flex-1 flex flex-col rounded-xl border border-border/70 bg-card/60 backdrop-blur-sm overflow-hidden shadow-xs">
      {/* Table Action Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 p-3 border-b border-border/80 bg-background/50">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Checkbox
              checked={allVisibleSelected}
              onCheckedChange={allVisibleSelected ? onClearSelection : onSelectAllVisible}
              aria-label="Select all visible"
            />
            <span className="text-xs font-semibold text-foreground">
              {mode === "company" ? "Verified Companies" : "Verified Decision-Makers"}
            </span>
            <Badge variant="secondary" className="text-[11px] px-2 py-0 bg-muted/80 text-muted-foreground border-border/60">
              {total.toLocaleString()} total
            </Badge>
          </div>

          {selectedIds.length > 0 && (
            <Badge variant="secondary" className="text-xs bg-primary/10 text-primary border-primary/20">
              {selectedIds.length} selected
            </Badge>
          )}
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Freshness & Sort Selector */}
          {onSortChange && (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground bg-muted/40 px-2 py-0.5 rounded-lg border border-border/60">
              <ArrowUpDown className="size-3 text-primary" />
              <span className="text-[11px] font-medium hidden md:inline">Sort:</span>
              <select
                value={currentSort || "recent"}
                onChange={(e) => onSortChange(e.target.value)}
                className="bg-transparent border-0 text-xs font-semibold text-foreground focus:outline-none cursor-pointer py-1 pr-1"
                aria-label="Sort by"
              >
                <option value="recent" className="bg-background text-foreground">Most Recent (Default)</option>
                {mode === "company" && <option value="rating" className="bg-background text-foreground">Highest Rating</option>}
                {mode === "company" && <option value="reviews" className="bg-background text-foreground">Most Reviews</option>}
                <option value="trust_score" className="bg-background text-foreground">Highest Trust</option>
                <option value="intent_score" className="bg-background text-foreground">Highest Intent</option>
              </select>
            </div>
          )}

          {selectedIds.length > 0 && (
            <Button
              size="sm"
              onClick={onPushToOneReachBatch}
              disabled={isPushing}
              className="h-8 text-xs font-medium bg-emerald-600 hover:bg-emerald-700 text-white gap-1.5 shadow-xs"
            >
              {isPushing ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Send className="size-3.5" />
              )}
              <span>Push to OneReach ({selectedIds.length})</span>
            </Button>
          )}

          {onResetSearch && (
            <Button
              variant="outline"
              size="sm"
              onClick={onResetSearch}
              className="h-8 text-xs gap-1.5 border-border/80 text-muted-foreground hover:text-foreground"
            >
              <Search className="size-3.5 text-primary" />
              <span>New Search</span>
            </Button>
          )}

          <Button
            variant="outline"
            size="sm"
            onClick={handleExportCsv}
            disabled={currentItems.length === 0}
            className="h-8 text-xs gap-1.5"
          >
            <Download className="size-3.5" />
            <span>Export CSV</span>
          </Button>
        </div>
      </div>

      {/* Main Table Content */}
      <div className="flex-1 overflow-x-auto min-h-[380px]">
        {isLoading ? (
          <div className="p-4 space-y-3">
            <div className="flex items-center gap-2 text-xs text-muted-foreground pb-2 border-b border-border/40">
              <Loader2 className="size-4 animate-spin text-primary" />
              <span>Querying verified records in PostgreSQL &amp; OpenSearch...</span>
            </div>
            <div className="space-y-2">
              {[1, 2, 3, 4, 5, 6].map((i) => (
                <div key={i} className="flex items-center gap-4 py-2.5 px-3 rounded-lg bg-muted/20 animate-pulse">
                  <div className="size-4 rounded bg-muted/60 shrink-0" />
                  <div className="size-7 rounded bg-muted/60 shrink-0" />
                  <div className="space-y-1.5 flex-1">
                    <div className="h-3 w-40 rounded bg-muted/70" />
                    <div className="h-2.5 w-24 rounded bg-muted/40" />
                  </div>
                  <div className="h-3 w-28 rounded bg-muted/50 hidden sm:block" />
                  <div className="h-3 w-16 rounded bg-muted/50 hidden md:block" />
                  <div className="h-3 w-20 rounded bg-muted/50 hidden lg:block" />
                  <div className="h-6 w-16 rounded bg-muted/60 shrink-0" />
                </div>
              ))}
            </div>
          </div>
        ) : currentItems.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 px-4 gap-3 text-muted-foreground">
            <div className="size-10 rounded-full bg-blue-500/10 flex items-center justify-center text-blue-600 dark:text-blue-400">
              <Sparkles className="size-5" />
            </div>
            <div className="text-center max-w-md">
              <p className="text-sm font-semibold text-foreground">No exact records match these active filters</p>
              <p className="text-xs text-muted-foreground mt-1">
                Explore master intelligence records nationwide or reset filters.
              </p>
            </div>
            <div className="flex items-center gap-2 mt-2">
              {onResetSearch && (
                <Button
                  size="sm"
                  variant="default"
                  onClick={onResetSearch}
                  className="h-8 text-xs font-semibold px-3 bg-primary text-primary-foreground gap-1.5 shadow-2xs"
                >
                  <RotateCcw className="size-3.5" />
                  <span>Reset All Filters</span>
                </Button>
              )}
            </div>
          </div>
        ) : mode === "company" ? (
          /* ================== COMPANY TABLE ================== */
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-border/80 bg-muted/40 font-semibold text-muted-foreground uppercase tracking-wider text-[11px]">
                <th className="w-10 px-3 py-2.5"></th>
                <th className="px-3 py-2.5">Company &amp; Domain</th>
                <th className="px-3 py-2.5">Industry</th>
                <th className="px-3 py-2.5">Rating &amp; Reviews</th>
                <th className="px-3 py-2.5">HQ Location</th>
                <th className="px-3 py-2.5">Headcount</th>
                <th className="px-3 py-2.5">Tech Stack</th>
                <th className="px-3 py-2.5">Intent Score</th>
                <th className="px-3 py-2.5">Trust</th>
                <th className="px-3 py-2.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {companies.map((company) => {
                const isSelected = selectedIds.includes(company.org_id);
                const isUpdatedToday = company.updated_at && (company.updated_at.startsWith("2026-11-22") || company.updated_at.startsWith("2026-11-23"));
                return (
                  <tr
                    key={company.org_id}
                    className={cn(
                      "group hover:bg-muted/40 transition-colors cursor-pointer",
                      isSelected && "bg-primary/5"
                    )}
                    onClick={() => onInspectCompany(company)}
                  >
                    <td
                      className="px-3 py-3"
                      onClick={(e) => {
                        e.stopPropagation();
                        onToggleSelectId(company.org_id);
                      }}
                    >
                      <Checkbox checked={isSelected} aria-label={`Select ${company.legal_name}`} />
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-2">
                        <div className="flex items-center justify-center size-7 rounded bg-blue-500/10 text-blue-600 dark:text-blue-400 font-bold text-xs shrink-0">
                          {company.legal_name.charAt(0).toUpperCase()}
                        </div>
                        <div className="truncate max-w-[210px]">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <Link
                              href={`/company/${company.org_id}${company.primary_domain ? `?domain=${encodeURIComponent(company.primary_domain)}` : ""}`}
                              onClick={(e) => e.stopPropagation()}
                              className="font-semibold text-foreground hover:text-primary hover:underline transition-colors truncate flex items-center gap-1 group/cname"
                              title="Open full Company Intelligence Page"
                            >
                              <span className="truncate">{company.legal_name}</span>
                              <ExternalLink className="size-2.5 opacity-0 group-hover/cname:opacity-100 transition-opacity shrink-0 text-muted-foreground" />
                            </Link>
                            {isUpdatedToday ? (
                              <span className="px-1.5 py-0.2 rounded text-[9px] font-semibold bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/25 shrink-0">
                                Updated today
                              </span>
                            ) : company.last_verified_at ? (
                              <span className="px-1.5 py-0.2 rounded text-[9px] font-medium bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/20 shrink-0">
                                Verified
                              </span>
                            ) : null}
                          </div>
                          {company.primary_domain ? (
                            <Link
                              href={`/company/${company.org_id}?domain=${encodeURIComponent(company.primary_domain)}`}
                              onClick={(e) => e.stopPropagation()}
                              className="text-[11px] text-muted-foreground hover:text-primary hover:underline truncate font-mono block"
                              title="Open Company Intelligence"
                            >
                              {company.primary_domain}
                            </Link>
                          ) : (
                            <p className="text-[11px] text-muted-foreground truncate font-mono">N/A</p>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <span className="truncate max-w-[140px] block text-muted-foreground">
                        {company.industry}
                      </span>
                    </td>
                    {/* Rating & Reviews Cell */}
                    <td className="px-3 py-3 whitespace-nowrap">
                      {company.rating ? (
                        <div className="flex items-center gap-1.5">
                          <div className="flex items-center text-amber-500 font-bold font-mono text-xs">
                            <Star className="size-3 fill-amber-500 text-amber-500 mr-0.5 shrink-0" />
                            <span>{Number(company.rating).toFixed(1)}</span>
                          </div>
                          <span className="text-[11px] text-muted-foreground font-sans">
                            ({company.review_count?.toLocaleString() || 0})
                          </span>
                        </div>
                      ) : (
                        <span className="text-muted-foreground/40 text-[11px]">—</span>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      <span className="font-mono text-foreground/80">
                        {company.city ? `${company.city}, ` : ""}
                        {company.state_code || company.jurisdiction || "US"}
                      </span>
                    </td>
                    <td className="px-3 py-3 font-mono tabnum text-muted-foreground">
                      <div>{company.employee_count_min} - {company.employee_count_max}</div>
                      {company.decision_maker_count && company.decision_maker_count > 0 ? (
                        <span className="text-[10px] text-purple-600 dark:text-purple-400 font-sans font-medium flex items-center gap-0.5 mt-0.5">
                          <Users className="size-2.5" />
                          {company.decision_maker_count} contacts
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-1 flex-wrap max-w-[180px]">
                        {company.technologies.slice(0, 2).map((t) => (
                          <Badge
                            key={t}
                            variant="secondary"
                            className="text-[10px] px-1.5 py-0 rounded bg-muted text-muted-foreground"
                          >
                            {t}
                          </Badge>
                        ))}
                        {company.technologies.length > 2 && (
                          <span className="text-[10px] text-muted-foreground">
                            +{company.technologies.length - 2}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-1.5">
                        <Flame
                          className={cn(
                            "size-3.5",
                            company.intent_score >= 80
                              ? "text-rose-500"
                              : company.intent_score >= 60
                              ? "text-amber-500"
                              : "text-blue-500"
                          )}
                        />
                        <span className="font-mono font-semibold tabnum">
                          {Math.round(company.intent_score)}
                        </span>
                        <span className="text-[10px] px-1 rounded bg-muted text-muted-foreground uppercase font-mono">
                          {company.intent_strength}
                        </span>
                      </div>
                    </td>
                    <td className="px-3 py-3 font-mono tabnum font-medium text-emerald-600 dark:text-emerald-400">
                      {Math.round(company.trust_score <= 1.0 ? company.trust_score * 100 : company.trust_score)}%
                    </td>
                    <td className="px-3 py-3 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/60"
                          onClick={(e) => {
                            e.stopPropagation();
                            onInspectCompany(company);
                          }}
                          title="Quick preview in slide-over drawer"
                        >
                          <span>Preview</span>
                        </Button>
                        <Button
                          asChild
                          variant="outline"
                          size="sm"
                          className="h-7 px-2.5 text-xs text-primary hover:text-primary-foreground hover:bg-primary gap-1 shadow-2xs font-medium"
                        >
                          <Link
                            href={`/company/${company.org_id}${company.primary_domain ? `?domain=${encodeURIComponent(company.primary_domain)}` : ""}`}
                            onClick={(e) => e.stopPropagation()}
                            title="Open full Company Intelligence page"
                          >
                            <span>Intelligence</span>
                            <ExternalLink className="size-3" />
                          </Link>
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          /* ================== PEOPLE TABLE ================== */
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b border-border/80 bg-muted/40 font-semibold text-muted-foreground uppercase tracking-wider text-[11px]">
                <th className="w-10 px-3 py-2.5"></th>
                <th className="px-3 py-2.5">Executive &amp; Title</th>
                <th className="px-3 py-2.5">Organization</th>
                <th className="px-3 py-2.5">Seniority / Dept</th>
                <th className="px-3 py-2.5">Email Status</th>
                <th className="px-3 py-2.5">Direct Phone</th>
                <th className="px-3 py-2.5">Location</th>
                <th className="px-3 py-2.5 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {people.map((person) => {
                const isSelected = selectedIds.includes(person.person_id);
                const isDeliverable =
                  person.deliverability_status.toLowerCase().includes("verified") ||
                  person.deliverability_status.toLowerCase().includes("deliverable");
                const isCatchAll =
                  person.deliverability_status.toLowerCase().includes("catch") || person.is_catch_all;

                return (
                  <tr
                    key={person.person_id}
                    className={cn(
                      "group hover:bg-muted/40 transition-colors cursor-pointer",
                      isSelected && "bg-primary/5"
                    )}
                    onClick={() => onInspectPerson(person)}
                  >
                    <td
                      className="px-3 py-3"
                      onClick={(e) => {
                        e.stopPropagation();
                        onToggleSelectId(person.person_id);
                      }}
                    >
                      <Checkbox checked={isSelected} aria-label={`Select ${person.full_name}`} />
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-2">
                        <div className="flex items-center justify-center size-7 rounded-full bg-purple-500/10 text-purple-600 dark:text-purple-400 font-bold text-xs shrink-0">
                          {person.full_name.charAt(0).toUpperCase()}
                        </div>
                        <div className="truncate max-w-[200px]">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <Link
                              href={`/leads/${person.person_id}`}
                              onClick={(e) => e.stopPropagation()}
                              className="font-semibold text-foreground hover:text-purple-600 dark:hover:text-purple-400 hover:underline transition-colors truncate flex items-center gap-1 group/pname"
                              title="Open full Lead Intelligence Dossier"
                            >
                              <span className="truncate">{person.full_name}</span>
                              <ExternalLink className="size-2.5 opacity-0 group-hover/pname:opacity-100 transition-opacity shrink-0 text-muted-foreground" />
                            </Link>
                            {person.updated_at && (person.updated_at.startsWith("2026-11-22") || person.updated_at.startsWith("2026-11-23")) ? (
                              <span className="px-1.5 py-0.2 rounded text-[9px] font-semibold bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/25 shrink-0">
                                Verified today
                              </span>
                            ) : (
                              <span className="px-1.5 py-0.2 rounded text-[9px] font-medium bg-purple-500/10 text-purple-600 dark:text-purple-400 border border-purple-500/20 shrink-0">
                                Verified
                              </span>
                            )}
                          </div>
                          <p className="text-[11px] text-muted-foreground truncate">{person.title}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <div className="truncate max-w-[160px]">
                        <Link
                          href={`/company/${person.company_id || encodeURIComponent(person.company_name)}${person.company_domain ? `?domain=${encodeURIComponent(person.company_domain)}` : ""}`}
                          onClick={(e) => e.stopPropagation()}
                          className="font-medium text-foreground hover:text-primary hover:underline transition-colors truncate block"
                          title="Open Company Intelligence"
                        >
                          {person.company_name}
                        </Link>
                        <p className="text-[11px] text-muted-foreground truncate font-mono">
                          {person.company_domain || "N/A"}
                        </p>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex flex-col gap-0.5">
                        <Badge
                          variant="secondary"
                          className="w-fit text-[10px] px-1.5 py-0 rounded bg-muted text-foreground/80 font-mono"
                        >
                          {person.seniority_level.replace("_", " ")}
                        </Badge>
                        <span className="text-[11px] text-muted-foreground truncate">
                          {person.department.replace("_", " ")}
                        </span>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-1.5">
                        {isDeliverable ? (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border border-emerald-500/30">
                            <CheckCircle2 className="size-3" />
                            <span>Verified</span>
                          </span>
                        ) : isCatchAll ? (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/15 text-amber-700 dark:text-amber-400 border border-amber-500/30">
                            <AlertCircle className="size-3" />
                            <span>Catch-All</span>
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold bg-rose-500/15 text-rose-700 dark:text-rose-400 border border-rose-500/30">
                            <HelpCircle className="size-3" />
                            <span>Risky</span>
                          </span>
                        )}
                        <Link
                          href={`/leads/${person.person_id}`}
                          onClick={(e) => e.stopPropagation()}
                          className="text-[11px] font-mono text-muted-foreground hover:text-foreground hover:underline truncate max-w-[120px]"
                          title="View Lead Profile"
                        >
                          {person.email}
                        </Link>
                      </div>
                    </td>
                    <td className="px-3 py-3 font-mono text-muted-foreground text-[11px]">
                      {person.phone || "—"}
                    </td>
                    <td className="px-3 py-3 font-mono text-[11px] text-foreground/80">
                      {person.city ? `${person.city}, ` : ""}
                      {person.state_code || "US"}
                    </td>
                    <td className="px-3 py-3 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/60"
                          onClick={(e) => {
                            e.stopPropagation();
                            onInspectPerson(person);
                          }}
                          title="Quick preview in slide-over drawer"
                        >
                          <span>Preview</span>
                        </Button>
                        <Button
                          asChild
                          variant="outline"
                          size="sm"
                          className="h-7 px-2.5 text-xs text-purple-600 dark:text-purple-400 hover:text-white hover:bg-purple-600 border-purple-500/30 gap-1 shadow-2xs font-medium"
                        >
                          <Link
                            href={`/leads/${person.person_id}`}
                            onClick={(e) => e.stopPropagation()}
                            title="Open full Lead Intelligence Dossier"
                          >
                            <span>Dossier</span>
                            <ExternalLink className="size-3" />
                          </Link>
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination Footer */}
      <div className="flex items-center justify-between p-3 border-t border-border/80 bg-background/50 text-xs">
        <span className="text-muted-foreground font-mono">
          Page {currentPage} of {totalPages}
        </span>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onPageChange(Math.max(0, offset - limit))}
            disabled={offset === 0 || isLoading}
            className="h-7 px-2 text-xs gap-1"
          >
            <ChevronLeft className="size-3.5" />
            <span>Prev</span>
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onPageChange(offset + limit)}
            disabled={offset + limit >= total || isLoading}
            className="h-7 px-2 text-xs gap-1"
          >
            <span>Next</span>
            <ChevronRight className="size-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}
