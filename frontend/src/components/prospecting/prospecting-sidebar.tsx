"use client";

import React, { useState, useMemo } from "react";
import {
  ChevronDown,
  ChevronRight,
  MapPin,
  Briefcase,
  Users,
  DollarSign,
  Cpu,
  ShieldCheck,
  Flame,
  UserCheck,
  Mail,
  Building,
  RotateCcw,
  Phone,
  Search,
  Globe,
  Award,
} from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ProspectingMode, CompanySearchParams, PeopleSearchParams } from "@/lib/prospecting-api";

interface ProspectingSidebarProps {
  mode: ProspectingMode;
  companyFilters: CompanySearchParams;
  onCompanyFiltersChange: (newFilters: CompanySearchParams) => void;
  peopleFilters: PeopleSearchParams;
  onPeopleFiltersChange: (newFilters: PeopleSearchParams) => void;
  facets: Record<string, { value: string; count: number }[]>;
  onResetFilters: () => void;
}

interface FilterSectionProps {
  title: string;
  icon: React.ElementType;
  defaultOpen?: boolean;
  activeCount?: number;
  children: React.ReactNode;
}

function FilterSection({
  title,
  icon: Icon,
  defaultOpen = true,
  activeCount = 0,
  children,
}: FilterSectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className="border-b border-border/60 py-2.5">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between text-left text-xs font-semibold text-foreground/90 hover:text-foreground transition-colors group"
      >
        <div className="flex items-center gap-2">
          <Icon className="size-3.5 text-muted-foreground group-hover:text-primary transition-colors" />
          <span>{title}</span>
          {activeCount > 0 && (
            <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-primary/15 text-primary font-bold">
              {activeCount}
            </span>
          )}
        </div>
        {isOpen ? (
          <ChevronDown className="size-3.5 text-muted-foreground" />
        ) : (
          <ChevronRight className="size-3.5 text-muted-foreground" />
        )}
      </button>
      {isOpen && <div className="mt-2 space-y-1.5">{children}</div>}
    </div>
  );
}

const DEFAULT_US_STATES = [
  "TX", "CA", "FL", "NY", "IL", "WA", "MA", "CO", "GA", "NC", "OH", "PA", "NJ", "VA", "AZ", "TN"
];

const DEFAULT_INDUSTRIES = [
  "Healthcare & Medical",
  "Homecare & Eldercare",
  "B2B SaaS & Software",
  "Commercial Services",
  "Banking and Finance",
  "Logistics & Transportation",
  "Artificial Intelligence",
  "Manufacturing & Industrial",
  "Public Corporation",
  "Federal Contractor",
];

const DEFAULT_TECHNOLOGIES = [
  "Salesforce",
  "AWS",
  "HubSpot",
  "Google Cloud",
  "React",
  "Stripe",
  "Microsoft Azure",
  "Docker",
  "PostgreSQL",
];

const DEFAULT_SENIORITIES = [
  { value: "C_SUITE", label: "C-Suite" },
  { value: "VP", label: "VP" },
  { value: "DIRECTOR", label: "Director" },
  { value: "MANAGER", label: "Manager" },
  { value: "FOUNDER", label: "Founder / Owner" },
  { value: "EXECUTIVE", label: "Executive" },
];

const DEFAULT_DEPARTMENTS = [
  { value: "SALES_MARKETING", label: "Sales & Marketing" },
  { value: "ENGINEERING_TECH", label: "Engineering & IT" },
  { value: "PRODUCT", label: "Product Management" },
  { value: "OPERATIONS", label: "Operations" },
  { value: "EXECUTIVE", label: "Executive Leadership" },
  { value: "RESEARCH", label: "Research & Science" },
];

export function ProspectingSidebar({
  mode,
  companyFilters,
  onCompanyFiltersChange,
  peopleFilters,
  onPeopleFiltersChange,
  onResetFilters,
}: ProspectingSidebarProps) {
  // Inline Search States for Facets
  const [locationSearch, setLocationSearch] = useState("");
  const [industrySearch, setIndustrySearch] = useState("");
  const [techSearch, setTechSearch] = useState("");
  const [titleInput, setTitleInput] = useState("");

  // Helpers for Company Mode
  const toggleCompanyState = (stateCode: string) => {
    const current = companyFilters.states || [];
    const next = current.includes(stateCode)
      ? current.filter((s) => s !== stateCode)
      : [...current, stateCode];
    onCompanyFiltersChange({ ...companyFilters, states: next.length ? next : undefined, offset: 0 });
  };

  const toggleCompanyIndustry = (industry: string) => {
    const current = companyFilters.industries || [];
    const next = current.includes(industry)
      ? current.filter((i) => i !== industry)
      : [...current, industry];
    onCompanyFiltersChange({ ...companyFilters, industries: next.length ? next : undefined, offset: 0 });
  };

  const toggleHeadcount = (range: string) => {
    const current = companyFilters.headcount_ranges || [];
    const next = current.includes(range)
      ? current.filter((r) => r !== range)
      : [...current, range];
    onCompanyFiltersChange({ ...companyFilters, headcount_ranges: next.length ? next : undefined, offset: 0 });
  };

  const toggleRevenue = (range: string) => {
    const current = companyFilters.revenue_ranges || [];
    const next = current.includes(range)
      ? current.filter((r) => r !== range)
      : [...current, range];
    onCompanyFiltersChange({ ...companyFilters, revenue_ranges: next.length ? next : undefined, offset: 0 });
  };

  const toggleFundingStage = (stage: string) => {
    const current = companyFilters.funding_stages || [];
    const next = current.includes(stage)
      ? current.filter((s) => s !== stage)
      : [...current, stage];
    onCompanyFiltersChange({ ...companyFilters, funding_stages: next.length ? next : undefined, offset: 0 });
  };

  const toggleTechnology = (tech: string) => {
    const current = companyFilters.technologies || [];
    const next = current.includes(tech)
      ? current.filter((t) => t !== tech)
      : [...current, tech];
    onCompanyFiltersChange({ ...companyFilters, technologies: next.length ? next : undefined, offset: 0 });
  };

  const toggleCompliance = (badge: string) => {
    const current = companyFilters.compliance_badges || [];
    const next = current.includes(badge)
      ? current.filter((b) => b !== badge)
      : [...current, badge];
    onCompanyFiltersChange({ ...companyFilters, compliance_badges: next.length ? next : undefined, offset: 0 });
  };

  const toggleIntentStrength = (strength: string) => {
    const current = companyFilters.intent_strengths || [];
    const next = current.includes(strength)
      ? current.filter((s) => s !== strength)
      : [...current, strength];
    onCompanyFiltersChange({ ...companyFilters, intent_strengths: next.length ? next : undefined, offset: 0 });
  };

  // Helpers for People Mode
  const toggleSeniority = (seniority: string) => {
    const current = peopleFilters.seniority_levels || [];
    const next = current.includes(seniority)
      ? current.filter((s) => s !== seniority)
      : [...current, seniority];
    onPeopleFiltersChange({ ...peopleFilters, seniority_levels: next.length ? next : undefined, offset: 0 });
  };

  const toggleDepartment = (dept: string) => {
    const current = peopleFilters.departments || [];
    const next = current.includes(dept)
      ? current.filter((d) => d !== dept)
      : [...current, dept];
    onPeopleFiltersChange({ ...peopleFilters, departments: next.length ? next : undefined, offset: 0 });
  };

  const togglePeopleState = (stateCode: string) => {
    const current = peopleFilters.states || [];
    const next = current.includes(stateCode)
      ? current.filter((s) => s !== stateCode)
      : [...current, stateCode];
    onPeopleFiltersChange({ ...peopleFilters, states: next.length ? next : undefined, offset: 0 });
  };

  const toggleEmailStatus = (status: string) => {
    const current = peopleFilters.email_statuses || [];
    const next = current.includes(status)
      ? current.filter((s) => s !== status)
      : [...current, status];
    onPeopleFiltersChange({ ...peopleFilters, email_statuses: next.length ? next : undefined, offset: 0 });
  };

  const toggleDirectPhone = () => {
    const nextVal = peopleFilters.has_phone ? undefined : true;
    onPeopleFiltersChange({ ...peopleFilters, has_phone: nextVal, offset: 0 });
  };

  const handleAddTitle = (title: string) => {
    const trimmed = title.trim();
    if (!trimmed) return;
    const current = peopleFilters.titles || [];
    if (!current.includes(trimmed)) {
      onPeopleFiltersChange({ ...peopleFilters, titles: [...current, trimmed], offset: 0 });
    }
    setTitleInput("");
  };

  const handleRemoveTitle = (title: string) => {
    const current = peopleFilters.titles || [];
    onPeopleFiltersChange({
      ...peopleFilters,
      titles: current.filter((t) => t !== title),
      offset: 0,
    });
  };

  // Filtered State Lists
  const filteredStates = useMemo(() => {
    if (!locationSearch) return DEFAULT_US_STATES;
    return DEFAULT_US_STATES.filter((s) =>
      s.toLowerCase().includes(locationSearch.toLowerCase())
    );
  }, [locationSearch]);

  const filteredIndustries = useMemo(() => {
    if (!industrySearch) return DEFAULT_INDUSTRIES;
    return DEFAULT_INDUSTRIES.filter((item) =>
      item.toLowerCase().includes(industrySearch.toLowerCase())
    );
  }, [industrySearch]);

  const filteredTechnologies = useMemo(() => {
    if (!techSearch) return DEFAULT_TECHNOLOGIES;
    return DEFAULT_TECHNOLOGIES.filter((item) =>
      item.toLowerCase().includes(techSearch.toLowerCase())
    );
  }, [techSearch]);

  return (
    <aside className="w-full md:w-64 lg:w-72 shrink-0 rounded-xl border border-border/70 bg-card/50 p-3.5 backdrop-blur-sm flex flex-col gap-1 text-sm shadow-2xs">
      {/* Sidebar Header */}
      <div className="flex items-center justify-between pb-2.5 border-b border-border/80">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-xs tracking-wider uppercase text-muted-foreground">
            Filters
          </span>
          <span className="text-[10px] text-muted-foreground font-mono bg-muted px-1.5 py-0.5 rounded">
            {mode === "company" ? "Organization" : "People"}
          </span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={onResetFilters}
          className="h-6 text-[11px] text-muted-foreground hover:text-foreground px-1.5 gap-1"
        >
          <RotateCcw className="size-3" />
          <span>Reset</span>
        </Button>
      </div>

      {mode === "company" ? (
        /* ================== COMPANY MODE FACETS ================== */
        <div className="space-y-0.5 overflow-y-auto max-h-[calc(100vh-220px)] pr-1">
          {/* Company Domain Filter */}
          <FilterSection
            title="Company Name / Domain"
            icon={Globe}
            activeCount={companyFilters.company_domain ? 1 : 0}
          >
            <div className="space-y-1">
              <Input
                value={companyFilters.company_domain || ""}
                onChange={(e) =>
                  onCompanyFiltersChange({
                    ...companyFilters,
                    company_domain: e.target.value ? e.target.value.trim() : undefined,
                    offset: 0,
                  })
                }
                placeholder="Include domain (e.g. apple.com)..."
                className="h-7 text-xs bg-background/80"
              />
            </div>
          </FilterSection>

          {/* Location (State & City) */}
          <FilterSection
            title="Location"
            icon={MapPin}
            activeCount={(companyFilters.states?.length || 0) + (companyFilters.cities?.length || 0)}
          >
            <div className="relative mb-1.5">
              <Search className="size-3 text-muted-foreground absolute left-2 top-2 pointer-events-none" />
              <Input
                value={locationSearch}
                onChange={(e) => setLocationSearch(e.target.value)}
                placeholder="Search state (e.g. TX, CA)..."
                className="h-7 pl-6 text-xs bg-background/80"
              />
            </div>
            <div className="space-y-1 max-h-36 overflow-y-auto pr-1">
              {filteredStates.map((st) => (
                <label
                  key={st}
                  className="flex items-center text-xs cursor-pointer py-1 px-1 rounded hover:bg-muted/50 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <Checkbox
                      checked={(companyFilters.states || []).includes(st)}
                      onCheckedChange={() => toggleCompanyState(st)}
                    />
                    <span>{st}</span>
                  </div>
                </label>
              ))}
            </div>
          </FilterSection>

          {/* Industry & Verticals */}
          <FilterSection
            title="Industry & Verticals"
            icon={Briefcase}
            activeCount={companyFilters.industries?.length || 0}
          >
            <div className="relative mb-1.5">
              <Search className="size-3 text-muted-foreground absolute left-2 top-2 pointer-events-none" />
              <Input
                value={industrySearch}
                onChange={(e) => setIndustrySearch(e.target.value)}
                placeholder="Search industry..."
                className="h-7 pl-6 text-xs bg-background/80"
              />
            </div>
            <div className="space-y-1 max-h-40 overflow-y-auto pr-1">
              {filteredIndustries.map((ind) => (
                <label
                  key={ind}
                  className="flex items-center text-xs cursor-pointer py-1 px-1 rounded hover:bg-muted/50 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <Checkbox
                      checked={(companyFilters.industries || []).includes(ind)}
                      onCheckedChange={() => toggleCompanyIndustry(ind)}
                    />
                    <span className="truncate max-w-[190px]">{ind}</span>
                  </div>
                </label>
              ))}
            </div>
          </FilterSection>

          {/* Employee Headcount */}
          <FilterSection
            title="Employee Headcount"
            icon={Users}
            activeCount={companyFilters.headcount_ranges?.length || 0}
          >
            {[
              { value: "1-10", label: "1 - 10" },
              { value: "11-50", label: "11 - 50" },
              { value: "51-200", label: "51 - 200" },
              { value: "201-500", label: "201 - 500" },
              { value: "501-1000", label: "501 - 1,000" },
              { value: "1000+", label: "1,000+" },
            ].map((hc) => (
              <label
                key={hc.value}
                className="flex items-center text-xs cursor-pointer py-1 px-1 rounded hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <Checkbox
                    checked={(companyFilters.headcount_ranges || []).includes(hc.value)}
                    onCheckedChange={() => toggleHeadcount(hc.value)}
                  />
                  <span>{hc.label}</span>
                </div>
              </label>
            ))}
          </FilterSection>

          {/* Annual Revenue */}
          <FilterSection
            title="Annual Revenue"
            icon={DollarSign}
            activeCount={companyFilters.revenue_ranges?.length || 0}
          >
            {[
              { value: "0-1M", label: "< $1M" },
              { value: "1M-10M", label: "$1M - $10M" },
              { value: "10M-50M", label: "$10M - $50M" },
              { value: "50M+", label: "$50M+" },
            ].map((rev) => (
              <label
                key={rev.value}
                className="flex items-center text-xs cursor-pointer py-1 px-1 rounded hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <Checkbox
                    checked={(companyFilters.revenue_ranges || []).includes(rev.value)}
                    onCheckedChange={() => toggleRevenue(rev.value)}
                  />
                  <span>{rev.label}</span>
                </div>
              </label>
            ))}
          </FilterSection>

          {/* Funding Stage */}
          <FilterSection
            title="Funding Stage"
            icon={Award}
            activeCount={companyFilters.funding_stages?.length || 0}
          >
            {[
              { value: "Seed", label: "Seed / Angel" },
              { value: "Series A", label: "Series A / Early" },
              { value: "Series B", label: "Series B & Later" },
              { value: "Public", label: "Public / IPO" },
              { value: "Bootstrapped", label: "Bootstrapped / Private" },
            ].map((stg) => (
              <label
                key={stg.value}
                className="flex items-center text-xs cursor-pointer py-1 px-1 rounded hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <Checkbox
                    checked={(companyFilters.funding_stages || []).includes(stg.value)}
                    onCheckedChange={() => toggleFundingStage(stg.value)}
                  />
                  <span>{stg.label}</span>
                </div>
              </label>
            ))}
          </FilterSection>

          {/* Technologies */}
          <FilterSection
            title="Technologies"
            icon={Cpu}
            activeCount={companyFilters.technologies?.length || 0}
          >
            <div className="relative mb-1.5">
              <Search className="size-3 text-muted-foreground absolute left-2 top-2 pointer-events-none" />
              <Input
                value={techSearch}
                onChange={(e) => setTechSearch(e.target.value)}
                placeholder="Search tech (e.g. AWS)..."
                className="h-7 pl-6 text-xs bg-background/80"
              />
            </div>
            <div className="space-y-1 max-h-36 overflow-y-auto pr-1">
              {filteredTechnologies.map((t) => (
                <label
                  key={t}
                  className="flex items-center text-xs cursor-pointer py-1 px-1 rounded hover:bg-muted/50 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <Checkbox
                      checked={(companyFilters.technologies || []).includes(t)}
                      onCheckedChange={() => toggleTechnology(t)}
                    />
                    <span className="truncate max-w-[190px]">{t}</span>
                  </div>
                </label>
              ))}
            </div>
          </FilterSection>

          {/* Compliance & Security */}
          <FilterSection
            title="Compliance & Security"
            icon={ShieldCheck}
            activeCount={companyFilters.compliance_badges?.length || 0}
          >
            {[
              { value: "SOC 2", label: "SOC 2 Certified" },
              { value: "HIPAA", label: "HIPAA Compliant" },
              { value: "ISO 27001", label: "ISO 27001" },
              { value: "GDPR", label: "GDPR Ready" },
            ].map((badge) => (
              <label
                key={badge.value}
                className="flex items-center text-xs cursor-pointer py-1 px-1 rounded hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <Checkbox
                    checked={(companyFilters.compliance_badges || []).includes(badge.value)}
                    onCheckedChange={() => toggleCompliance(badge.value)}
                  />
                  <span>{badge.label}</span>
                </div>
              </label>
            ))}
          </FilterSection>

          {/* Buyer Intent Signals */}
          <FilterSection
            title="Buyer Intent Signals"
            icon={Flame}
            activeCount={companyFilters.intent_strengths?.length || 0}
          >
            {["SURGING", "HIGH", "MEDIUM"].map((strength) => (
              <label
                key={strength}
                className="flex items-center text-xs cursor-pointer py-1 px-1 rounded hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <Checkbox
                    checked={(companyFilters.intent_strengths || []).includes(strength)}
                    onCheckedChange={() => toggleIntentStrength(strength)}
                  />
                  <span>{strength} Intent</span>
                </div>
              </label>
            ))}
          </FilterSection>
        </div>
      ) : (
        /* ================== PEOPLE MODE FACETS ================== */
        <div className="space-y-0.5 overflow-y-auto max-h-[calc(100vh-220px)] pr-1">
          {/* Job Titles Filter */}
          <FilterSection
            title="Job Titles"
            icon={Briefcase}
            activeCount={peopleFilters.titles?.length || 0}
          >
            <div className="space-y-2">
              <div className="flex gap-1.5">
                <Input
                  value={titleInput}
                  onChange={(e) => setTitleInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleAddTitle(titleInput);
                    }
                  }}
                  placeholder="e.g. CTO, VP, Founder..."
                  className="h-7 text-xs bg-background/80"
                />
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => handleAddTitle(titleInput)}
                  className="h-7 text-xs px-2 shrink-0"
                >
                  Add
                </Button>
              </div>

              {/* Active Title Tags */}
              {peopleFilters.titles && peopleFilters.titles.length > 0 && (
                <div className="flex flex-wrap gap-1 pt-1">
                  {peopleFilters.titles.map((t) => (
                    <Badge
                      key={t}
                      variant="secondary"
                      className="text-[10px] pl-2 pr-1 py-0.5 gap-1 font-normal"
                    >
                      <span>{t}</span>
                      <button
                        type="button"
                        onClick={() => handleRemoveTitle(t)}
                        className="hover:text-destructive text-muted-foreground"
                      >
                        ×
                      </button>
                    </Badge>
                  ))}
                </div>
              )}

              {/* Quick Preset Title Buttons */}
              <div className="flex flex-wrap gap-1 pt-1">
                {["CEO", "CTO", "Founder", "VP Sales", "VP Engineering"].map((quick) => (
                  <button
                    key={quick}
                    type="button"
                    onClick={() => handleAddTitle(quick)}
                    className="text-[10px] px-1.5 py-0.5 rounded border border-border/70 hover:border-primary/50 bg-background text-muted-foreground hover:text-foreground transition-all"
                  >
                    + {quick}
                  </button>
                ))}
              </div>
            </div>
          </FilterSection>

          {/* Direct Phone Numbers */}
          <FilterSection
            title="Direct Phone Numbers"
            icon={Phone}
            activeCount={peopleFilters.has_phone ? 1 : 0}
          >
            <label className="flex items-center text-xs cursor-pointer py-1.5 px-1 rounded hover:bg-muted/50 transition-colors">
              <div className="flex items-center gap-2">
                <Checkbox
                  checked={Boolean(peopleFilters.has_phone)}
                  onCheckedChange={toggleDirectPhone}
                />
                <span className="font-medium text-foreground">Has Direct Phone Number</span>
              </div>
            </label>
          </FilterSection>

          {/* Seniority Levels */}
          <FilterSection
            title="Seniority Levels"
            icon={UserCheck}
            activeCount={peopleFilters.seniority_levels?.length || 0}
          >
            {DEFAULT_SENIORITIES.map((s) => (
              <label
                key={s.value}
                className="flex items-center text-xs cursor-pointer py-1 px-1 rounded hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <Checkbox
                    checked={(peopleFilters.seniority_levels || []).includes(s.value)}
                    onCheckedChange={() => toggleSeniority(s.value)}
                  />
                  <span>{s.label}</span>
                </div>
              </label>
            ))}
          </FilterSection>

          {/* Departments */}
          <FilterSection
            title="Departments"
            icon={Users}
            activeCount={peopleFilters.departments?.length || 0}
          >
            {DEFAULT_DEPARTMENTS.map((d) => (
              <label
                key={d.value}
                className="flex items-center text-xs cursor-pointer py-1 px-1 rounded hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <Checkbox
                    checked={(peopleFilters.departments || []).includes(d.value)}
                    onCheckedChange={() => toggleDepartment(d.value)}
                  />
                  <span>{d.label}</span>
                </div>
              </label>
            ))}
          </FilterSection>

          {/* Person Location */}
          <FilterSection
            title="Location"
            icon={MapPin}
            activeCount={peopleFilters.states?.length || 0}
          >
            <div className="relative mb-1.5">
              <Search className="size-3 text-muted-foreground absolute left-2 top-2 pointer-events-none" />
              <Input
                value={locationSearch}
                onChange={(e) => setLocationSearch(e.target.value)}
                placeholder="Search state (e.g. CA, NY)..."
                className="h-7 pl-6 text-xs bg-background/80"
              />
            </div>
            <div className="space-y-1 max-h-36 overflow-y-auto pr-1">
              {filteredStates.map((st) => (
                <label
                  key={st}
                  className="flex items-center text-xs cursor-pointer py-1 px-1 rounded hover:bg-muted/50 transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <Checkbox
                      checked={(peopleFilters.states || []).includes(st)}
                      onCheckedChange={() => togglePeopleState(st)}
                    />
                    <span>{st}</span>
                  </div>
                </label>
              ))}
            </div>
          </FilterSection>

          {/* Email Deliverability */}
          <FilterSection
            title="Email Deliverability"
            icon={Mail}
            activeCount={peopleFilters.email_statuses?.length || 0}
          >
            {[
              { value: "VERIFIED", label: "Verified Deliverable" },
              { value: "CATCH_ALL", label: "Catch-All / Accept All" },
              { value: "RISKY", label: "Risky / Low Score" },
            ].map((es) => (
              <label
                key={es.value}
                className="flex items-center text-xs cursor-pointer py-1 px-1 rounded hover:bg-muted/50 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <Checkbox
                    checked={(peopleFilters.email_statuses || []).includes(es.value)}
                    onCheckedChange={() => toggleEmailStatus(es.value)}
                  />
                  <span>{es.label}</span>
                </div>
              </label>
            ))}
          </FilterSection>

          {/* Employer Domain */}
          <FilterSection
            title="Employer Domain"
            icon={Building}
            activeCount={peopleFilters.company_domain ? 1 : 0}
          >
            <Input
              value={peopleFilters.company_domain || ""}
              onChange={(e) =>
                onPeopleFiltersChange({
                  ...peopleFilters,
                  company_domain: e.target.value ? e.target.value.trim() : undefined,
                  offset: 0,
                })
              }
              placeholder="e.g. google.com, stripe.com..."
              className="h-7 text-xs bg-background/80"
            />
          </FilterSection>
        </div>
      )}
    </aside>
  );
}
