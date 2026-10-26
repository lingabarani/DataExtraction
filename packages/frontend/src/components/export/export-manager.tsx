"use client";
import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Select, SelectContent, SelectItem,
  SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Download, FileText, FileSpreadsheet, FileJson,
  Globe2, Filter, CheckSquare, Square, Loader2,
  Database, ShieldCheck, Phone, Users, AlertCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

// ── Column definitions ────────────────────────────────────────────────────────

interface ColDef {
  key:       string;
  label:     string;
  group:     "person" | "company" | "contact" | "meta";
  default:   boolean;
}

const COLUMNS: ColDef[] = [
  // Person
  { key: "full_name",             label: "Full Name",            group: "person",  default: true  },
  { key: "first_name",            label: "First Name",           group: "person",  default: false },
  { key: "last_name",             label: "Last Name",            group: "person",  default: false },
  { key: "title",                 label: "Title",                group: "person",  default: true  },
  { key: "standardized_title",    label: "Standardized Title",   group: "person",  default: false },
  { key: "seniority_level",       label: "Seniority Level",      group: "person",  default: true  },
  { key: "department",            label: "Department",           group: "person",  default: false },
  { key: "linkedin_url",          label: "LinkedIn URL",         group: "person",  default: true  },
  // Contact
  { key: "email",                 label: "Email",                group: "contact", default: true  },
  { key: "email_status",          label: "Email Status",         group: "contact", default: true  },
  { key: "email_confidence_score",label: "Email Score",          group: "contact", default: false },
  { key: "phone",                 label: "Phone",                group: "contact", default: true  },
  // Company
  { key: "company_name",          label: "Company Name",         group: "company", default: true  },
  { key: "domain",                label: "Domain",               group: "company", default: true  },
  { key: "industry",              label: "Industry",             group: "company", default: true  },
  { key: "naics_code",            label: "NAICS Code",           group: "company", default: false },
  { key: "ein",                   label: "EIN",                  group: "company", default: false },
  { key: "employee_band",         label: "Employee Band",        group: "company", default: false },
  // Location
  { key: "city",                  label: "City",                 group: "company", default: true  },
  { key: "state_code",            label: "State",                group: "company", default: true  },
  { key: "zip_code",              label: "ZIP Code",             group: "company", default: false },
  { key: "country",               label: "Country",              group: "company", default: false },
  // Meta
  { key: "lead_score",            label: "Lead Score",           group: "meta",    default: true  },
  { key: "api_source",            label: "Data Source",          group: "meta",    default: true  },
  { key: "created_at",            label: "Created At",           group: "meta",    default: false },
];

const GROUP_LABELS = {
  person:  "Person",
  contact: "Contact",
  company: "Company / Location",
  meta:    "Meta",
};

const GROUP_COLORS = {
  person:  "text-blue-500",
  contact: "text-green-500",
  company: "text-amber-500",
  meta:    "text-violet-500",
};

// ── Preset column sets ────────────────────────────────────────────────────────

const PRESETS: Record<string, string[]> = {
  "Email Outreach":  ["full_name","title","email","email_status","company_name","industry","seniority_level"],
  "Phone Outreach":  ["full_name","title","phone","company_name","city","state_code","seniority_level"],
  "CRM Import":      ["full_name","first_name","last_name","email","phone","company_name","domain","title","seniority_level","city","state_code","lead_score"],
  "Full Export":     COLUMNS.map(c => c.key),
  "Minimal":         ["full_name","email","phone","company_name"],
};

// ── Estimated record count from filters ──────────────────────────────────────

interface FilterState {
  table:        "us_leads" | "mexico_leads";
  seniority:    string;
  industry:     string;
  state_code:   string;
  email_status: string;
  api_source:   string;
}

// ── Main component ────────────────────────────────────────────────────────────

export function ExportManager() {
  const [filters, setFilters] = useState<FilterState>({
    table: "us_leads", seniority: "all", industry: "all",
    state_code: "all", email_status: "all", api_source: "all",
  });
  const [selectedCols, setSelectedCols] = useState<Set<string>>(
    new Set(COLUMNS.filter(c => c.default).map(c => c.key))
  );
  const [format,      setFormat]      = useState<"csv" | "json" | "xlsx">("csv");
  const [estimating,  setEstimating]  = useState(false);
  const [estimate,    setEstimate]    = useState<number | null>(null);
  const [downloading, setDownloading] = useState(false);

  // ── Fetch record estimate when filters change ─────────────────────────────
  useEffect(() => {
    setEstimating(true);
    const params = new URLSearchParams();
    params.set("table", filters.table);
    params.set("limit", "1");
    if (filters.seniority    !== "all") params.set("seniority",    filters.seniority);
    if (filters.industry     !== "all") params.set("industry",     filters.industry);
    if (filters.state_code   !== "all") params.set("state_code",   filters.state_code);
    if (filters.email_status !== "all") params.set("email_status", filters.email_status);
    if (filters.api_source   !== "all") params.set("api_source",   filters.api_source);

    api.get<{ total: number }>(`/leads/count?${params}`)
      .then(r => setEstimate(r.total))
      .catch(() => setEstimate(null))
      .finally(() => setEstimating(false));
  }, [filters]);

  // ── Column toggles ────────────────────────────────────────────────────────
  const toggleCol = (key: string) => {
    setSelectedCols(prev => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  const applyPreset = (name: string) => {
    setSelectedCols(new Set(PRESETS[name] ?? []));
  };

  const toggleGroup = (group: ColDef["group"]) => {
    const groupKeys = COLUMNS.filter(c => c.group === group).map(c => c.key);
    const allOn = groupKeys.every(k => selectedCols.has(k));
    setSelectedCols(prev => {
      const next = new Set(prev);
      groupKeys.forEach(k => allOn ? next.delete(k) : next.add(k));
      return next;
    });
  };

  // ── Download ──────────────────────────────────────────────────────────────
  const handleDownload = async () => {
    setDownloading(true);
    try {
      const params = new URLSearchParams();
      params.set("table",   filters.table);
      params.set("format",  format);
      params.set("columns", Array.from(selectedCols).join(","));
      if (filters.seniority    !== "all") params.set("seniority",    filters.seniority);
      if (filters.industry     !== "all") params.set("industry",     filters.industry);
      if (filters.state_code   !== "all") params.set("state_code",   filters.state_code);
      if (filters.email_status !== "all") params.set("email_status", filters.email_status);
      if (filters.api_source   !== "all") params.set("api_source",   filters.api_source);

      const filename = `oneextraction_${filters.table}_${new Date().toISOString().slice(0,10)}.${format}`;
      await api.download(`/export/leads?${params}`, filename);
      toast.success(`Downloaded ${filename}`);
    } catch (e) {
      toast.error(`Export failed: ${e}`);
    } finally {
      setDownloading(false);
    }
  };

  const setFilter = <K extends keyof FilterState>(key: K, val: FilterState[K]) =>
    setFilters(prev => ({ ...prev, [key]: val }));

  const groups = (["person","contact","company","meta"] as const);

  return (
    <div className="space-y-5 max-w-5xl">
      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-primary/10">
            <Download className="w-5 h-5 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Export Data</h1>
            <p className="text-muted-foreground text-sm">
              Filter, choose columns, and download your leads as CSV, JSON, or Excel.
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">

        {/* ── Left: Filters ─────────────────────────────────────────── */}
        <div className="lg:col-span-1 space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <Filter className="w-4 h-4 text-primary" /> Filters
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 pt-0">

              {/* Table */}
              <div>
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1 block">
                  Dataset
                </label>
                <Select value={filters.table} onValueChange={v => setFilter("table", v as FilterState["table"])}>
                  <SelectTrigger className="h-9 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="us_leads">
                      <div className="flex items-center gap-2">
                        <Globe2 className="w-3.5 h-3.5 text-blue-500" /> US Leads (906K+)
                      </div>
                    </SelectItem>
                    <SelectItem value="mexico_leads">
                      <div className="flex items-center gap-2">
                        <Globe2 className="w-3.5 h-3.5 text-green-500" /> Mexico Leads (50K+)
                      </div>
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Seniority */}
              <div>
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1 block">
                  Seniority
                </label>
                <Select value={filters.seniority} onValueChange={v => setFilter("seniority", v)}>
                  <SelectTrigger className="h-9 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All seniority</SelectItem>
                    <SelectItem value="C_SUITE">C-Suite</SelectItem>
                    <SelectItem value="VP">VP</SelectItem>
                    <SelectItem value="DIRECTOR">Director</SelectItem>
                    <SelectItem value="MANAGER">Manager</SelectItem>
                    <SelectItem value="FOUNDER">Founder</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Industry */}
              <div>
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1 block">
                  Industry
                </label>
                <Select value={filters.industry} onValueChange={v => setFilter("industry", v)}>
                  <SelectTrigger className="h-9 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All industries</SelectItem>
                    <SelectItem value="Healthcare">Healthcare</SelectItem>
                    <SelectItem value="Banking and Finance">Banking & Finance</SelectItem>
                    <SelectItem value="Computer Software">Technology</SelectItem>
                    <SelectItem value="Federal Contractor">Federal Contractor</SelectItem>
                    <SelectItem value="Nonprofits and Associations">Nonprofits</SelectItem>
                    <SelectItem value="Industrial Manufacturing & Transformation">Manufacturing</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* State */}
              <div>
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1 block">
                  State
                </label>
                <Select value={filters.state_code} onValueChange={v => setFilter("state_code", v)}>
                  <SelectTrigger className="h-9 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All states</SelectItem>
                    {["CA","TX","NY","FL","IL","PA","OH","GA","WA","AZ"].map(s => (
                      <SelectItem key={s} value={s}>{s}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Email status */}
              <div>
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1 block">
                  Email Status
                </label>
                <Select value={filters.email_status} onValueChange={v => setFilter("email_status", v)}>
                  <SelectTrigger className="h-9 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All email status</SelectItem>
                    <SelectItem value="VERIFIED">✅ Verified (Deliverable / MX)</SelectItem>
                    <SelectItem value="DELIVERABLE">🎯 Deliverable (SMTP Proof)</SelectItem>
                    <SelectItem value="MX_CONFIRMED">🛡️ MX Confirmed</SelectItem>
                    <SelectItem value="RISKY">⚠️ Risky (Role/Catch-all)</SelectItem>
                    <SelectItem value="MISSING">— No email</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Source */}
              <div>
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1 block">
                  Data Source
                </label>
                <Select value={filters.api_source} onValueChange={v => setFilter("api_source", v)}>
                  <SelectTrigger className="h-9 text-xs"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All sources</SelectItem>
                    <SelectItem value="CMS_NPI">CMS NPI</SelectItem>
                    <SelectItem value="SEC_EDGAR">SEC EDGAR</SelectItem>
                    <SelectItem value="FDIC">FDIC Banks</SelectItem>
                    <SelectItem value="USASPENDING">USASpending</SelectItem>
                    <SelectItem value="PROPUBLICA_990">ProPublica 990</SelectItem>
                    <SelectItem value="SAM_GOV">SAM.gov</SelectItem>
                    <SelectItem value="CSV">CSV Import</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <Separator />

              {/* Estimate */}
              <div className="flex items-center gap-2 py-1">
                <Database className="w-4 h-4 text-primary flex-shrink-0" />
                <div>
                  <p className="text-xs text-muted-foreground">Matching records</p>
                  {estimating
                    ? <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground mt-0.5" />
                    : <p className="text-lg font-bold text-primary">
                        {estimate != null ? estimate.toLocaleString() : "—"}
                      </p>
                  }
                </div>
              </div>

              {estimate != null && estimate > 100_000 && (
                <div className="flex items-start gap-2 p-2 rounded-lg bg-amber-500/10 border border-amber-200">
                  <AlertCircle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0 mt-0.5" />
                  <p className="text-xs text-amber-700 dark:text-amber-400">
                    Large export — may take a few minutes to generate.
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* ── Right: Column selector + download ─────────────────────── */}
        <div className="lg:col-span-2 space-y-4">

          {/* Presets */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">Column Presets</CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="flex flex-wrap gap-2">
                {Object.keys(PRESETS).map(name => (
                  <Button
                    key={name}
                    variant="outline"
                    size="sm"
                    className="h-8 text-xs"
                    onClick={() => applyPreset(name)}
                  >
                    {name}
                  </Button>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Column selector */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm">Select Columns</CardTitle>
                <span className="text-xs text-muted-foreground">
                  {selectedCols.size} / {COLUMNS.length} selected
                </span>
              </div>
            </CardHeader>
            <CardContent className="pt-0 space-y-4">
              {groups.map(group => {
                const cols      = COLUMNS.filter(c => c.group === group);
                const allOn     = cols.every(c => selectedCols.has(c.key));
                const someOn    = cols.some(c => selectedCols.has(c.key));
                return (
                  <div key={group}>
                    {/* Group header */}
                    <button
                      onClick={() => toggleGroup(group)}
                      className="flex items-center gap-2 mb-2 w-full group"
                    >
                      {allOn
                        ? <CheckSquare className={`w-3.5 h-3.5 ${GROUP_COLORS[group]}`} />
                        : someOn
                          ? <CheckSquare className="w-3.5 h-3.5 text-muted-foreground/60" />
                          : <Square className="w-3.5 h-3.5 text-muted-foreground/40" />
                      }
                      <span className={`text-xs font-semibold uppercase tracking-wide ${GROUP_COLORS[group]}`}>
                        {GROUP_LABELS[group]}
                      </span>
                    </button>
                    {/* Columns */}
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5 pl-5">
                      {cols.map(col => (
                        <button
                          key={col.key}
                          onClick={() => toggleCol(col.key)}
                          className={`
                            flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs
                            border transition-all text-left
                            ${selectedCols.has(col.key)
                              ? "bg-primary/10 border-primary/40 text-primary font-medium"
                              : "bg-muted/30 border-border text-muted-foreground hover:bg-muted"
                            }
                          `}
                        >
                          {selectedCols.has(col.key)
                            ? <CheckSquare className="w-3 h-3 flex-shrink-0" />
                            : <Square      className="w-3 h-3 flex-shrink-0" />
                          }
                          {col.label}
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>

          {/* Format + Download */}
          <Card>
            <CardContent className="pt-4 pb-4">
              <div className="flex items-center gap-3 flex-wrap">
                <div>
                  <p className="text-xs text-muted-foreground mb-2">Export format</p>
                  <div className="flex gap-2">
                    {([
                      { fmt: "csv",  icon: FileText,        label: "CSV"   },
                      { fmt: "xlsx", icon: FileSpreadsheet,  label: "Excel" },
                      { fmt: "json", icon: FileJson,         label: "JSON"  },
                    ] as const).map(({ fmt, icon: Icon, label }) => (
                      <button
                        key={fmt}
                        onClick={() => setFormat(fmt)}
                        className={`
                          flex items-center gap-1.5 px-3 py-2 rounded-lg border text-xs font-medium
                          transition-all
                          ${format === fmt
                            ? "bg-primary text-primary-foreground border-primary"
                            : "bg-muted/30 border-border hover:bg-muted text-muted-foreground"
                          }
                        `}
                      >
                        <Icon className="w-3.5 h-3.5" /> {label}
                      </button>
                    ))}
                  </div>
                </div>

                <Button
                  variant="gradient"
                  size="lg"
                  className="ml-auto"
                  onClick={handleDownload}
                  disabled={downloading || selectedCols.size === 0}
                >
                  {downloading
                    ? <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Generating...</>
                    : <><Download className="w-4 h-4 mr-2" />
                        Download {estimate != null ? `${estimate.toLocaleString()} records` : ""}
                      </>
                  }
                </Button>
              </div>

              {/* Summary */}
              <div className="flex flex-wrap gap-3 mt-3 pt-3 border-t text-xs text-muted-foreground">
                <span className="flex items-center gap-1">
                  <Database className="w-3 h-3" />
                  {filters.table === "us_leads" ? "US Leads" : "Mexico Leads"}
                </span>
                <span className="flex items-center gap-1">
                  <CheckSquare className="w-3 h-3" />
                  {selectedCols.size} columns
                </span>
                {(filters.email_status === "VERIFIED" || filters.email_status === "DELIVERABLE" || filters.email_status === "MX_CONFIRMED") && (
                  <span className="flex items-center gap-1 text-emerald-600">
                    <ShieldCheck className="w-3 h-3" /> {filters.email_status === "DELIVERABLE" ? "SMTP Deliverable only" : filters.email_status === "MX_CONFIRMED" ? "MX Confirmed only" : "Verified email only"}
                  </span>
                )}
                {filters.seniority !== "all" && (
                  <span className="flex items-center gap-1">
                    <Users className="w-3 h-3" /> {filters.seniority}
                  </span>
                )}
                {filters.state_code !== "all" && (
                  <span className="flex items-center gap-1">
                    <Globe2 className="w-3 h-3" /> {filters.state_code}
                  </span>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
