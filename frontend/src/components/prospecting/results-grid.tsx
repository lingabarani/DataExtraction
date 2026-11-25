"use client";

import React, { useEffect, useRef } from "react";
import Link from "next/link";
import {
  ExternalLink,
  Send,
  Download,
  Mail,
  Loader2,
  Sparkles,
  RotateCcw,
  X,
} from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ProspectingMode,
  CompanyRecord,
  PeopleRecord,
} from "@/lib/prospecting-api";
import {
  formatEmployeeBadge,
  formatRelativeSync,
  formatRevenueBadge,
  normalizePercentScore,
} from "@/lib/formatters";
import { cn } from "@/lib/utils";

interface ResultsGridProps {
  mode: ProspectingMode;
  companies: CompanyRecord[];
  people: PeopleRecord[];
  total: number;
  limit: number;
  offset: number;
  isLoading: boolean;
  isLoadingMore?: boolean;
  hasMore?: boolean;
  onLoadMore?: () => void;
  selectedIds: string[];
  currentSort?: string;
  onSortChange?: (newSort: string) => void;
  onToggleSelectId: (id: string) => void;
  onSelectAllVisible: () => void;
  onClearSelection: () => void;
  onPageChange?: (newOffset: number) => void;
  onPreviewCompany?: (company: CompanyRecord) => void;
  onPreviewPerson?: (person: PeopleRecord) => void;
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
  isLoading,
  isLoadingMore = false,
  hasMore = false,
  onLoadMore,
  selectedIds,
  onToggleSelectId,
  onSelectAllVisible,
  onClearSelection,
  onPreviewCompany,
  onPreviewPerson,
  onInspectCompany,
  onInspectPerson,
  onPushToOneReachBatch,
  isPushing,
  onResetSearch,
}: ResultsGridProps) {
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  const currentItems = mode === "company" ? companies : people;
  const allVisibleSelected =
    currentItems.length > 0 &&
    currentItems.every((item) =>
      selectedIds.includes(
        mode === "company"
          ? (item as CompanyRecord).org_id
          : (item as PeopleRecord).person_id
      )
    );

  // Infinite Scroll Observer
  useEffect(() => {
    if (!hasMore || isLoading || isLoadingMore || !onLoadMore) return;
    const node = sentinelRef.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          onLoadMore();
        }
      },
      { rootMargin: "240px" }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasMore, isLoading, isLoadingMore, onLoadMore]);

  const handleExportSelectedOrVisibleCsv = () => {
    const sourceRows =
      selectedIds.length > 0
        ? currentItems.filter((item) =>
            selectedIds.includes(
              mode === "company"
                ? (item as CompanyRecord).org_id
                : (item as PeopleRecord).person_id
            )
          )
        : currentItems;

    if (sourceRows.length === 0) return;

    const header =
      mode === "company"
        ? "Org ID,Company Name,Domain,Industry,Revenue,Employees,Trust Score,Last Synced\n"
        : "Person ID,Name,Title,Company,Email,Seniority,Department,Location\n";

    const rows =
      mode === "company"
        ? (sourceRows as CompanyRecord[])
            .map((c) => {
              const trust = normalizePercentScore(c.trust_score, 85);
              return `"${c.org_id}","${c.legal_name}","${c.primary_domain || ""}","${c.sub_industry || c.industry || ""}","${formatRevenueBadge(c.annual_revenue_usd)}","${formatEmployeeBadge(c.employee_count_min, c.employee_count_max)}",${trust}%,"${c.last_verified_at || c.updated_at || ""}"`;
            })
            .join("\n")
        : (sourceRows as PeopleRecord[])
            .map(
              (p) =>
                `"${p.person_id}","${p.full_name || ""}","${p.title || ""}","${p.company_name || ""}","${p.email || ""}","${(p.seniority_level || p.seniority || "C_SUITE").replace(/_/g, " ")}","${(p.department || "Executive").replace(/_/g, " ")}","${p.city ? `${p.city}, ` : ""}${p.state_code || "US"}"`
            )
            .join("\n");

    const blob = new Blob([header + rows], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `dataextraction_${mode}_export.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <div className="w-full flex flex-col rounded-2xl border border-border/80 bg-card shadow-card overflow-hidden">
        {/* Table Toolbar */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-5 py-4 border-b border-border/80 bg-muted/20">
          <div className="flex items-center gap-3">
            <Checkbox
              checked={allVisibleSelected}
              onCheckedChange={allVisibleSelected ? onClearSelection : onSelectAllVisible}
              aria-label="Select all visible rows"
            />
            <h2 className="text-sm font-semibold text-foreground">
              {mode === "company" ? "Company Intelligence Directory" : "Executive Decision-Makers"}
            </h2>
            <span className="text-meta text-muted-foreground tabular-nums">
              Showing {currentItems.length.toLocaleString("en-US")} of{" "}
              {total.toLocaleString("en-US")}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleExportSelectedOrVisibleCsv}
              disabled={currentItems.length === 0}
              className="h-9 rounded-xl px-3 text-xs font-medium gap-1.5"
            >
              <Download className="size-3.5" />
              <span>Export CSV</span>
            </Button>
          </div>
        </div>

        {/* Table Body */}
        <div className="w-full overflow-x-auto scrollbar-enterprise">
          {isLoading ? (
            <div className="p-6 flex flex-col gap-3">
              {[1, 2, 3, 4, 5, 6].map((i) => (
                <div
                  key={i}
                  className="flex items-center gap-4 rounded-xl border border-border/50 bg-muted/20 px-4 py-4"
                >
                  <Skeleton className="size-5 rounded-md shrink-0" />
                  <Skeleton className="size-10 rounded-xl shrink-0" />
                  <div className="flex-1 flex flex-col gap-2">
                    <Skeleton className="h-4 w-48" />
                    <Skeleton className="h-3 w-32" />
                  </div>
                  <Skeleton className="h-6 w-28 rounded-lg hidden md:block" />
                  <Skeleton className="h-6 w-20 rounded-lg hidden lg:block" />
                  <Skeleton className="h-2.5 w-28 rounded-full hidden sm:block" />
                </div>
              ))}
            </div>
          ) : currentItems.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 px-6 gap-4 text-center">
              <div className="flex size-12 items-center justify-center rounded-2xl bg-primary/10 text-primary">
                <Sparkles className="size-6" aria-hidden="true" />
              </div>
              <div className="max-w-md flex flex-col gap-1">
                <p className="text-base font-semibold text-foreground">
                  No matching records found
                </p>
                <p className="text-sm text-muted-foreground">
                  Broaden your semantic prompt or reset active filters to explore verified Master Vault intelligence.
                </p>
              </div>
              {onResetSearch && (
                <Button
                  type="button"
                  onClick={onResetSearch}
                  className="h-10 rounded-xl px-4 text-sm font-medium gap-2"
                >
                  <RotateCcw className="size-4" />
                  <span>Reset Search &amp; Filters</span>
                </Button>
              )}
            </div>
          ) : mode === "company" ? (
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-border bg-muted/35 text-xs font-semibold text-muted-foreground">
                  <th className="w-12 px-4 py-3.5" />
                  <th className="px-4 py-3.5 min-w-[260px]">Company &amp; Domain</th>
                  <th className="px-4 py-3.5 min-w-[160px]">Industry</th>
                  <th className="px-4 py-3.5 min-w-[120px]">Revenue</th>
                  <th className="px-4 py-3.5 min-w-[130px]">Employees</th>
                  <th className="px-4 py-3.5 min-w-[160px]">Trust Score</th>
                  <th className="px-4 py-3.5 min-w-[110px]">Sources</th>
                  <th className="px-4 py-3.5 min-w-[120px]">Last Synced</th>
                  <th className="px-4 py-3.5 text-right min-w-[140px]">Details</th>
                </tr>
              </thead>
              <tbody>
                {companies.map((company) => {
                  const isSelected = selectedIds.includes(company.org_id);
                  const trustPct = normalizePercentScore(company.trust_score, 85);
                  const rawSourceCount = (company as unknown as { source_count?: number }).source_count;
                  const sourceCount =
                    typeof rawSourceCount === "number" && rawSourceCount > 0
                      ? rawSourceCount
                      : company.technologies?.length
                        ? Math.min(5, company.technologies.length + 1)
                        : 1;

                  return (
                    <tr
                      key={company.org_id}
                      onClick={() =>
                        onPreviewCompany ? onPreviewCompany(company) : onInspectCompany(company)
                      }
                      className={cn(
                        "group cursor-pointer border-b border-border/60 transition-colors duration-200",
                        "odd:bg-card even:bg-slate-50/70 dark:even:bg-slate-900/35",
                        "hover:bg-primary/[0.04] dark:hover:bg-primary/[0.08]",
                        isSelected && "bg-primary/[0.06] dark:bg-primary/[0.12]"
                      )}
                    >
                      <td
                        className="px-4 py-4"
                        onClick={(e) => {
                          e.stopPropagation();
                          onToggleSelectId(company.org_id);
                        }}
                      >
                        <Checkbox
                          checked={isSelected}
                          aria-label={`Select ${company.legal_name}`}
                        />
                      </td>

                      {/* Logo/Avatar + Legal Name + Domain */}
                      <td className="px-4 py-4">
                        <div className="flex items-center gap-3.5 min-w-0">
                          <Avatar className="size-10 rounded-xl border border-border/70 shrink-0">
                            <AvatarFallback className="rounded-xl bg-primary/10 text-sm font-semibold text-primary">
                              {company.legal_name.charAt(0).toUpperCase()}
                            </AvatarFallback>
                          </Avatar>
                          <div className="min-w-0 max-w-[230px]">
                            <p
                              className="truncate text-sm font-semibold text-foreground group-hover:text-primary transition-colors"
                              title={company.legal_name}
                            >
                              {company.legal_name}
                            </p>
                            {company.primary_domain ? (
                              <a
                                href={
                                  company.primary_domain.startsWith("http")
                                    ? company.primary_domain
                                    : `https://${company.primary_domain}`
                                }
                                target="_blank"
                                rel="noopener noreferrer"
                                onClick={(e) => e.stopPropagation()}
                                className="inline-flex items-center gap-1 text-xs font-mono text-muted-foreground hover:text-primary hover:underline truncate max-w-full"
                              >
                                <span className="truncate">{company.primary_domain}</span>
                                <ExternalLink className="size-3 shrink-0 opacity-60" />
                              </a>
                            ) : (
                              <span className="text-xs font-mono text-muted-foreground/60">
                                Domain unlisted
                              </span>
                            )}
                          </div>
                        </div>
                      </td>

                      {/* Industry Badge */}
                      <td className="px-4 py-4">
                        <Badge
                          variant="secondary"
                          className="rounded-lg px-2.5 py-1 text-xs font-medium max-w-[180px] truncate"
                          title={company.sub_industry || company.industry}
                        >
                          {company.sub_industry || company.industry || "Commercial"}
                        </Badge>
                      </td>

                      {/* Revenue Badge */}
                      <td className="px-4 py-4">
                        <Badge
                          variant="outline"
                          className="rounded-lg px-2.5 py-1 text-xs font-medium tabular-nums whitespace-nowrap"
                        >
                          {formatRevenueBadge(company.annual_revenue_usd)}
                        </Badge>
                      </td>

                      {/* Employee Badge */}
                      <td className="px-4 py-4">
                        <Badge
                          variant="outline"
                          className="rounded-lg px-2.5 py-1 text-xs font-medium tabular-nums whitespace-nowrap"
                        >
                          {formatEmployeeBadge(
                            company.employee_count_min,
                            company.employee_count_max
                          )}
                        </Badge>
                      </td>

                      {/* Trust Score Progress Bar */}
                      <td className="px-4 py-4">
                        <div className="flex items-center gap-2.5 min-w-[130px]">
                          <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                            <div
                              className={cn(
                                "h-full rounded-full",
                                trustPct >= 80
                                  ? "bg-success"
                                  : trustPct >= 50
                                    ? "bg-warning"
                                    : "bg-destructive"
                              )}
                              style={{ width: `${trustPct}%` }}
                            />
                          </div>
                          <span className="w-9 text-right text-xs font-semibold text-foreground tabular-nums">
                            {trustPct}%
                          </span>
                        </div>
                      </td>

                      {/* Source Count */}
                      <td className="px-4 py-4">
                        <span className="inline-flex items-center rounded-lg bg-muted/70 px-2.5 py-1 text-xs font-medium text-foreground tabular-nums whitespace-nowrap">
                          {sourceCount} {sourceCount === 1 ? "source" : "sources"}
                        </span>
                      </td>

                      {/* Last Synced */}
                      <td className="px-4 py-4 text-xs text-muted-foreground tabular-nums whitespace-nowrap">
                        {formatRelativeSync(company.last_verified_at || company.updated_at)}
                      </td>

                      {/* Actions */}
                      <td
                        className="px-4 py-4 text-right whitespace-nowrap"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className="inline-flex items-center gap-1.5">
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => onInspectCompany(company)}
                            className="h-8 rounded-lg px-3 text-xs font-medium gap-1.5"
                          >
                            <Sparkles className="size-3.5 text-primary" />
                            <span>Inspect</span>
                          </Button>
                          <Button
                            asChild
                            variant="ghost"
                            size="icon"
                            className="size-8 rounded-lg text-muted-foreground hover:text-foreground"
                          >
                            <Link
                              href={`/company/${company.org_id}${company.primary_domain ? `?domain=${encodeURIComponent(company.primary_domain)}` : ""}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              aria-label={`Open ${company.legal_name} full dossier`}
                            >
                              <ExternalLink className="size-3.5" />
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
            /* People Hybrid Table */
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-border bg-muted/35 text-xs font-semibold text-muted-foreground">
                  <th className="w-12 px-4 py-3.5" />
                  <th className="px-4 py-3.5 min-w-[240px]">Executive &amp; Title</th>
                  <th className="px-4 py-3.5 min-w-[180px]">Company</th>
                  <th className="px-4 py-3.5 min-w-[140px]">Seniority</th>
                  <th className="px-4 py-3.5 min-w-[200px]">Work Email</th>
                  <th className="px-4 py-3.5 min-w-[130px]">Direct Phone</th>
                  <th className="px-4 py-3.5 min-w-[110px]">Location</th>
                  <th className="px-4 py-3.5 text-right min-w-[140px]">Details</th>
                </tr>
              </thead>
              <tbody>
                {people.map((person) => {
                  const isSelected = selectedIds.includes(person.person_id);
                  const fullNameDisplay = person.full_name || "Executive";
                  return (
                    <tr
                      key={person.person_id}
                      onClick={() =>
                        onPreviewPerson ? onPreviewPerson(person) : onInspectPerson(person)
                      }
                      className={cn(
                        "group cursor-pointer border-b border-border/60 transition-colors duration-200",
                        "odd:bg-card even:bg-slate-50/70 dark:even:bg-slate-900/35",
                        "hover:bg-primary/[0.04] dark:hover:bg-primary/[0.08]",
                        isSelected && "bg-primary/[0.06] dark:bg-primary/[0.12]"
                      )}
                    >
                      <td
                        className="px-4 py-4"
                        onClick={(e) => {
                          e.stopPropagation();
                          onToggleSelectId(person.person_id);
                        }}
                      >
                        <Checkbox
                          checked={isSelected}
                          aria-label={`Select ${fullNameDisplay}`}
                        />
                      </td>

                      <td className="px-4 py-4">
                        <div className="flex items-center gap-3.5">
                          <Avatar className="size-10 rounded-full border border-border/70 shrink-0">
                            <AvatarFallback className="rounded-full bg-primary/10 text-sm font-semibold text-primary">
                              {fullNameDisplay.charAt(0).toUpperCase()}
                            </AvatarFallback>
                          </Avatar>
                          <div className="min-w-0 max-w-[210px]">
                            <p className="truncate text-sm font-semibold text-foreground group-hover:text-primary transition-colors">
                              {fullNameDisplay}
                            </p>
                            <p className="truncate text-xs text-muted-foreground">
                              {person.title || "Decision-Maker"}
                            </p>
                          </div>
                        </div>
                      </td>

                      <td className="px-4 py-4">
                        <p className="truncate max-w-[180px] text-sm font-medium text-foreground">
                          {person.company_name || "Organization"}
                        </p>
                        <p className="truncate max-w-[180px] text-xs font-mono text-muted-foreground">
                          {person.company_domain || "—"}
                        </p>
                      </td>

                      <td className="px-4 py-4">
                        <Badge variant="secondary" className="rounded-lg text-xs font-medium">
                          {(person.seniority_level || person.seniority || "C_SUITE").replace(/_/g, " ")}
                        </Badge>
                      </td>

                      <td className="px-4 py-4">
                        {person.email ? (
                          <a
                            href={`mailto:${person.email}`}
                            onClick={(e) => e.stopPropagation()}
                            className="inline-flex items-center gap-1.5 text-xs font-mono text-foreground hover:text-primary hover:underline truncate max-w-[200px]"
                          >
                            <Mail className="size-3.5 text-muted-foreground shrink-0" />
                            <span className="truncate">{person.email}</span>
                          </a>
                        ) : (
                          <span className="text-xs text-muted-foreground/50">—</span>
                        )}
                      </td>

                      <td className="px-4 py-4 text-xs font-mono text-muted-foreground whitespace-nowrap">
                        {person.phone || "—"}
                      </td>

                      <td className="px-4 py-4 text-xs text-muted-foreground whitespace-nowrap">
                        {person.city ? `${person.city}, ` : ""}
                        {person.state_code || "US"}
                      </td>

                      <td
                        className="px-4 py-4 text-right whitespace-nowrap"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <div className="inline-flex items-center gap-1.5">
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => onInspectPerson(person)}
                            className="h-8 rounded-lg px-3 text-xs font-medium gap-1.5"
                          >
                            <Sparkles className="size-3.5 text-primary" />
                            <span>Inspect</span>
                          </Button>
                          <Button
                            asChild
                            variant="ghost"
                            size="icon"
                            className="size-8 rounded-lg text-muted-foreground hover:text-foreground"
                          >
                            <Link
                              href={`/leads/${person.person_id}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              aria-label={`Open ${fullNameDisplay} dossier`}
                            >
                              <ExternalLink className="size-3.5" />
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

        {/* Infinite Scroll Sentinel & Load-More Fallback */}
        {!isLoading && currentItems.length > 0 && (
          <div
            ref={sentinelRef}
            className="flex items-center justify-center border-t border-border/60 bg-muted/15 px-5 py-4"
          >
            {isLoadingMore ? (
              <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
                <Loader2 className="size-4 animate-spin text-primary" />
                <span>Loading more verified records...</span>
              </div>
            ) : hasMore && onLoadMore ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={onLoadMore}
                className="h-9 rounded-xl px-4 text-xs font-medium"
              >
                Load More ({(total - currentItems.length).toLocaleString("en-US")} remaining)
              </Button>
            ) : (
              <span className="text-xs text-muted-foreground">
                End of results · {currentItems.length.toLocaleString("en-US")} records loaded
              </span>
            )}
          </div>
        )}
      </div>

      {/* Floating Multi-Select Bulk Action Bar */}
      {selectedIds.length > 0 && (
        <div
          role="region"
          aria-label="Bulk selection actions"
          className="fixed bottom-6 left-1/2 -translate-x-1/2 z-30 flex items-center gap-3 rounded-2xl border border-border/40 bg-slate-900 px-5 py-3 text-white shadow-card-md dark:bg-slate-800 animate-slide-up"
        >
          <span className="text-sm font-semibold tabular-nums">
            {selectedIds.length} selected
          </span>
          <div className="h-4 w-px bg-white/20" />
          <Button
            type="button"
            size="sm"
            onClick={onPushToOneReachBatch}
            disabled={isPushing}
            className="h-8 rounded-xl bg-success hover:bg-success/90 text-white px-3 text-xs font-medium gap-1.5"
          >
            {isPushing ? <Loader2 className="size-3.5 animate-spin" /> : <Send className="size-3.5" />}
            <span>Push to OneReach</span>
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={handleExportSelectedOrVisibleCsv}
            className="h-8 rounded-xl px-3 text-xs font-medium gap-1.5"
          >
            <Download className="size-3.5" />
            <span>Export CSV</span>
          </Button>
          <button
            type="button"
            onClick={onClearSelection}
            className="rounded-lg p-1.5 text-slate-300 hover:bg-white/10 hover:text-white transition-colors"
            aria-label="Clear selection"
          >
            <X className="size-4" />
          </button>
        </div>
      )}
    </>
  );
}
