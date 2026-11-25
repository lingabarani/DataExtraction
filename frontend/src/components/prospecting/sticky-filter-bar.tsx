"use client";

import * as React from "react";
import {
  MapPin,
  Briefcase,
  DollarSign,
  Users,
  ShieldCheck,
  SlidersHorizontal,
  ArrowUpDown,
  Check,
  ChevronDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { ProspectingSidebar } from "@/components/prospecting/prospecting-sidebar";
import type {
  ProspectingMode,
  CompanySearchParams,
  PeopleSearchParams,
  FacetItem,
} from "@/lib/prospecting-api";
import { cn } from "@/lib/utils";

const TOP_STATES = ["CA", "TX", "NY", "FL", "IL", "OH", "WA", "MA", "PA", "GA"];

const TOP_INDUSTRIES = [
  "Healthcare & Life Sciences",
  "Homecare & Eldercare",
  "B2B SaaS & Software",
  "Commercial Services",
  "Banking & Finance",
  "Logistics & Transportation",
  "Manufacturing & Industrial",
];

const REVENUE_RANGES = ["$1M-$10M", "$10M-$50M", "$50M-$250M", "$250M+"];
const HEADCOUNT_RANGES = ["1-10", "11-50", "51-200", "201-500", "501-1000", "1000+"];
const TRUST_THRESHOLDS = [
  { label: "90%+ High Trust", value: 90 },
  { label: "80%+ Verified", value: 80 },
  { label: "60%+ Baseline", value: 60 },
];

const SENIORITIES = [
  { value: "C_SUITE", label: "C-Suite" },
  { value: "FOUNDER", label: "Founder / Owner" },
  { value: "VP", label: "Vice President" },
  { value: "DIRECTOR", label: "Director" },
  { value: "MANAGER", label: "Manager" },
];

const DEPARTMENTS = [
  { value: "EXECUTIVE", label: "Executive Leadership" },
  { value: "ENGINEERING_TECH", label: "Engineering & IT" },
  { value: "SALES_MARKETING", label: "Sales & Marketing" },
  { value: "OPERATIONS", label: "Operations" },
  { value: "FINANCE", label: "Finance" },
];

interface StickyFilterBarProps {
  mode: ProspectingMode;
  companyFilters: CompanySearchParams;
  onCompanyFiltersChange: (next: CompanySearchParams) => void;
  peopleFilters: PeopleSearchParams;
  onPeopleFiltersChange: (next: PeopleSearchParams) => void;
  facets: Record<string, FacetItem[]>;
  total: number;
  currentSort: string;
  onSortChange: (sort: string) => void;
  onResetFilters: () => void;
}

export function StickyFilterBar({
  mode,
  companyFilters,
  onCompanyFiltersChange,
  peopleFilters,
  onPeopleFiltersChange,
  facets,
  total,
  currentSort,
  onSortChange,
  onResetFilters,
}: StickyFilterBarProps) {
  const toggleCompanyItem = (
    key: "states" | "industries" | "revenue_ranges" | "headcount_ranges",
    value: string
  ) => {
    const existing = companyFilters[key] || [];
    const next = existing.includes(value)
      ? existing.filter((v) => v !== value)
      : [...existing, value];
    onCompanyFiltersChange({
      ...companyFilters,
      [key]: next.length ? next : undefined,
      offset: 0,
    });
  };

  const togglePeopleItem = (
    key: "states" | "seniority_levels" | "departments",
    value: string
  ) => {
    const existing = peopleFilters[key] || [];
    const next = existing.includes(value)
      ? existing.filter((v) => v !== value)
      : [...existing, value];
    onPeopleFiltersChange({
      ...peopleFilters,
      [key]: next.length ? next : undefined,
      offset: 0,
    });
  };

  return (
    <div className="sticky top-0 z-10 flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-2xl border border-border/80 glass-surface px-4 py-3 shadow-card">
      {/* Filter Triggers */}
      <div className="flex items-center gap-2 flex-wrap">
        {/* State / Region */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              className={cn(
                "h-9 rounded-xl px-3 text-xs font-medium gap-1.5",
                ((mode === "company" ? companyFilters.states : peopleFilters.states)?.length ?? 0) > 0 &&
                  "border-primary/40 bg-primary/5 text-primary"
              )}
            >
              <MapPin className="size-3.5" aria-hidden="true" />
              <span>Location</span>
              <ChevronDown className="size-3 opacity-60" aria-hidden="true" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-52 rounded-xl p-1.5">
            <DropdownMenuLabel className="text-xs text-muted-foreground">US States</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <div className="grid grid-cols-2 gap-1">
              {TOP_STATES.map((st) => {
                const active = (mode === "company" ? companyFilters.states : peopleFilters.states)?.includes(st);
                return (
                  <DropdownMenuItem
                    key={st}
                    onClick={() =>
                      mode === "company"
                        ? toggleCompanyItem("states", st)
                        : togglePeopleItem("states", st)
                    }
                    className="rounded-lg flex items-center justify-between text-xs cursor-pointer"
                  >
                    <span>{st}</span>
                    {active && <Check className="size-3.5 text-primary" />}
                  </DropdownMenuItem>
                );
              })}
            </div>
          </DropdownMenuContent>
        </DropdownMenu>

        {mode === "company" ? (
          <>
            {/* Industry Filter */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className={cn(
                    "h-9 rounded-xl px-3 text-xs font-medium gap-1.5",
                    (companyFilters.industries?.length ?? 0) > 0 &&
                      "border-primary/40 bg-primary/5 text-primary"
                  )}
                >
                  <Briefcase className="size-3.5" aria-hidden="true" />
                  <span>Industry</span>
                  <ChevronDown className="size-3 opacity-60" aria-hidden="true" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-64 rounded-xl p-1.5">
                <DropdownMenuLabel className="text-xs text-muted-foreground">Verticals</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {TOP_INDUSTRIES.map((ind) => {
                  const active = companyFilters.industries?.includes(ind);
                  return (
                    <DropdownMenuItem
                      key={ind}
                      onClick={() => toggleCompanyItem("industries", ind)}
                      className="rounded-lg flex items-center justify-between text-xs cursor-pointer"
                    >
                      <span className="truncate">{ind}</span>
                      {active && <Check className="size-3.5 text-primary shrink-0" />}
                    </DropdownMenuItem>
                  );
                })}
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Revenue Filter */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className={cn(
                    "h-9 rounded-xl px-3 text-xs font-medium gap-1.5",
                    (companyFilters.revenue_ranges?.length ?? 0) > 0 &&
                      "border-primary/40 bg-primary/5 text-primary"
                  )}
                >
                  <DollarSign className="size-3.5" aria-hidden="true" />
                  <span>Revenue</span>
                  <ChevronDown className="size-3 opacity-60" aria-hidden="true" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-48 rounded-xl p-1.5">
                <DropdownMenuLabel className="text-xs text-muted-foreground">Annual Revenue</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {REVENUE_RANGES.map((rev) => {
                  const active = companyFilters.revenue_ranges?.includes(rev);
                  return (
                    <DropdownMenuItem
                      key={rev}
                      onClick={() => toggleCompanyItem("revenue_ranges", rev)}
                      className="rounded-lg flex items-center justify-between text-xs cursor-pointer"
                    >
                      <span>{rev}</span>
                      {active && <Check className="size-3.5 text-primary" />}
                    </DropdownMenuItem>
                  );
                })}
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Employees Filter */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className={cn(
                    "h-9 rounded-xl px-3 text-xs font-medium gap-1.5",
                    (companyFilters.headcount_ranges?.length ?? 0) > 0 &&
                      "border-primary/40 bg-primary/5 text-primary"
                  )}
                >
                  <Users className="size-3.5" aria-hidden="true" />
                  <span>Employees</span>
                  <ChevronDown className="size-3 opacity-60" aria-hidden="true" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-48 rounded-xl p-1.5">
                <DropdownMenuLabel className="text-xs text-muted-foreground">Headcount</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {HEADCOUNT_RANGES.map((hc) => {
                  const active = companyFilters.headcount_ranges?.includes(hc);
                  return (
                    <DropdownMenuItem
                      key={hc}
                      onClick={() => toggleCompanyItem("headcount_ranges", hc)}
                      className="rounded-lg flex items-center justify-between text-xs cursor-pointer"
                    >
                      <span>{hc} employees</span>
                      {active && <Check className="size-3.5 text-primary" />}
                    </DropdownMenuItem>
                  );
                })}
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Trust Score Filter */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className={cn(
                    "h-9 rounded-xl px-3 text-xs font-medium gap-1.5",
                    companyFilters.min_trust_score !== undefined &&
                      "border-primary/40 bg-primary/5 text-primary"
                  )}
                >
                  <ShieldCheck className="size-3.5" aria-hidden="true" />
                  <span>Trust Score</span>
                  <ChevronDown className="size-3 opacity-60" aria-hidden="true" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-48 rounded-xl p-1.5">
                <DropdownMenuLabel className="text-xs text-muted-foreground">Minimum Trust</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {TRUST_THRESHOLDS.map((t) => {
                  const active = companyFilters.min_trust_score === t.value;
                  return (
                    <DropdownMenuItem
                      key={t.value}
                      onClick={() =>
                        onCompanyFiltersChange({
                          ...companyFilters,
                          min_trust_score: active ? undefined : t.value,
                          offset: 0,
                        })
                      }
                      className="rounded-lg flex items-center justify-between text-xs cursor-pointer"
                    >
                      <span>{t.label}</span>
                      {active && <Check className="size-3.5 text-primary" />}
                    </DropdownMenuItem>
                  );
                })}
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        ) : (
          <>
            {/* Seniority Filter */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className={cn(
                    "h-9 rounded-xl px-3 text-xs font-medium gap-1.5",
                    (peopleFilters.seniority_levels?.length ?? 0) > 0 &&
                      "border-primary/40 bg-primary/5 text-primary"
                  )}
                >
                  <Users className="size-3.5" aria-hidden="true" />
                  <span>Seniority</span>
                  <ChevronDown className="size-3 opacity-60" aria-hidden="true" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-52 rounded-xl p-1.5">
                <DropdownMenuLabel className="text-xs text-muted-foreground">Leadership Level</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {SENIORITIES.map((sen) => {
                  const active = peopleFilters.seniority_levels?.includes(sen.value);
                  return (
                    <DropdownMenuItem
                      key={sen.value}
                      onClick={() => togglePeopleItem("seniority_levels", sen.value)}
                      className="rounded-lg flex items-center justify-between text-xs cursor-pointer"
                    >
                      <span>{sen.label}</span>
                      {active && <Check className="size-3.5 text-primary" />}
                    </DropdownMenuItem>
                  );
                })}
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Department Filter */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className={cn(
                    "h-9 rounded-xl px-3 text-xs font-medium gap-1.5",
                    (peopleFilters.departments?.length ?? 0) > 0 &&
                      "border-primary/40 bg-primary/5 text-primary"
                  )}
                >
                  <Briefcase className="size-3.5" aria-hidden="true" />
                  <span>Department</span>
                  <ChevronDown className="size-3 opacity-60" aria-hidden="true" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-56 rounded-xl p-1.5">
                <DropdownMenuLabel className="text-xs text-muted-foreground">Function</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {DEPARTMENTS.map((dept) => {
                  const active = peopleFilters.departments?.includes(dept.value);
                  return (
                    <DropdownMenuItem
                      key={dept.value}
                      onClick={() => togglePeopleItem("departments", dept.value)}
                      className="rounded-lg flex items-center justify-between text-xs cursor-pointer"
                    >
                      <span>{dept.label}</span>
                      {active && <Check className="size-3.5 text-primary" />}
                    </DropdownMenuItem>
                  );
                })}
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        )}

        {/* Full Facet Filter Drawer (Preserves All Advanced Facets) */}
        <Sheet>
          <SheetTrigger asChild>
            <Button variant="ghost" size="sm" className="h-9 rounded-xl px-3 text-xs font-medium gap-1.5">
              <SlidersHorizontal className="size-3.5" aria-hidden="true" />
              <span>All Filters</span>
            </Button>
          </SheetTrigger>
          <SheetContent side="left" className="p-0 w-full sm:max-w-sm overflow-y-auto scrollbar-enterprise">
            <SheetHeader className="p-5 border-b border-border">
              <SheetTitle>Advanced Filters</SheetTitle>
              <SheetDescription>
                Refine {mode === "company" ? "company firmographics" : "executive criteria"} with full facets.
              </SheetDescription>
            </SheetHeader>
            <div className="p-4">
              <ProspectingSidebar
                mode={mode}
                companyFilters={companyFilters}
                onCompanyFiltersChange={onCompanyFiltersChange}
                peopleFilters={peopleFilters}
                onPeopleFiltersChange={onPeopleFiltersChange}
                facets={facets}
                onResetFilters={onResetFilters}
              />
            </div>
          </SheetContent>
        </Sheet>
      </div>

      {/* Right Side: Match Summary & Sort Selector */}
      <div className="flex items-center gap-3 shrink-0">
        <span className="text-xs font-medium text-muted-foreground tabular-nums">
          {total.toLocaleString("en-US")} {mode === "company" ? "organizations" : "contacts"}
        </span>

        <div className="flex items-center gap-1.5 rounded-xl border border-border bg-background px-3 h-9">
          <ArrowUpDown className="size-3.5 text-muted-foreground" aria-hidden="true" />
          <select
            value={currentSort}
            onChange={(e) => onSortChange(e.target.value)}
            aria-label="Sort results"
            className="bg-transparent text-xs font-medium text-foreground focus:outline-none cursor-pointer pr-1"
          >
            <option value="recent">Most Recent</option>
            {mode === "company" && <option value="rating">Highest Rating</option>}
            {mode === "company" && <option value="reviews">Most Reviews</option>}
            <option value="trust_score">Highest Trust Score</option>
            <option value="intent_score">Highest Intent</option>
          </select>
        </div>
      </div>
    </div>
  );
}
