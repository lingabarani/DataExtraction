"use client";
import { useState, useCallback, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem,
  SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Search, X, Download, ChevronLeft, ChevronRight,
  SlidersHorizontal, Loader2, Table as TableIcon, MapPin,
} from "lucide-react";
import dynamic from "next/dynamic";
import { useLeads, type LeadFilter } from "@/hooks/use-leads";
import { LeadsTable } from "./leads-table";
import { api } from "@/lib/api";

const LeadsMap = dynamic(() => import("./leads-map").then((m) => m.LeadsMap), {
  ssr: false,
  loading: () => (
    <div className="h-[500px] w-full flex items-center justify-center border rounded-lg bg-muted/20 text-muted-foreground text-sm">
      Loading interactive map...
    </div>
  ),
});

// ── Quick filter pill definitions ────────────────────────────────────────────

interface Pill {
  label:  string;
  filter: Partial<LeadFilter>;
}

const PILLS: Pill[] = [
  { label: "Economic Buyer",  filter: { buying_role: "ECONOMIC_BUYER" } },
  { label: "Tech Evaluator",  filter: { buying_role: "TECHNICAL_EVALUATOR" } },
  { label: "Champion",        filter: { buying_role: "CHAMPION" } },
  { label: "Surging Intent",  filter: { intent_strength: "SURGING" } },
  { label: "High Intent",     filter: { intent_strength: "HIGH" } },
  { label: "C-Suite",         filter: { seniority: "C_SUITE" } },
  { label: "VP",              filter: { seniority: "VP" } },
  { label: "Director",        filter: { seniority: "DIRECTOR" } },
  { label: "Verified Email",  filter: { email_status: "VERIFIED" } },
  { label: "Technology",      filter: { industry: "Computer Software" } },
  { label: "Healthcare",      filter: { industry: "Healthcare" } },
  { label: "Banking",         filter: { industry: "Banking and Finance" } },
];

// ── AI example queries ────────────────────────────────────────────────────────

const AI_EXAMPLES = [
  "CEOs in Texas healthcare with verified email",
  "CFOs in California technology",
  "VP level banking New York",
  "Founders manufacturing sector",
];

// ── FilterSelect — compact labelled select ────────────────────────────────────

function FilterSelect({
  label, value, onValueChange, children,
}: {
  label:         string;
  value:         string;
  onValueChange: (v: string) => void;
  children:      React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-0 border border-border rounded overflow-hidden">
      <span className="px-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground bg-muted/60 border-r border-border whitespace-nowrap h-8 flex items-center select-none">
        {label}
      </span>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger className="h-8 border-0 rounded-none text-[12px] shadow-none focus:ring-0 min-w-[110px] bg-transparent">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {children}
        </SelectContent>
      </Select>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  table?: "us_leads" | "mexico_leads";
}

export function LeadsList({ table = "us_leads" }: Props) {
  // ── Filter state ───────────────────────────────────────────────────────────
  const [nlQuery,     setNlQuery]     = useState("");
  const [inputValue,  setInputValue]  = useState("");
  const [isThinking,  setIsThinking]  = useState(false);
  const [activePills, setActivePills] = useState<number[]>([]);
  const [seniority,   setSeniority]   = useState("all");
  const [industry,    setIndustry]    = useState("all");
  const [stateCode,   setStateCode]   = useState("all");
  const [emailStatus, setEmailStatus] = useState("all");
  const [page,        setPage]        = useState(1);
  const [showFilters, setShowFilters] = useState(false);
  const [viewMode,    setViewMode]    = useState<"table" | "map">("table");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Merge pill filters ─────────────────────────────────────────────────────
  const pillFilter = activePills.reduce<Partial<LeadFilter>>(
    (acc, idx) => ({ ...acc, ...PILLS[idx].filter }), {}
  );

  const filter: LeadFilter = {
    table,
    page,
    limit: 50,
    nl_query:        nlQuery      || undefined,
    seniority:       pillFilter.seniority       || (seniority    !== "all" ? seniority    : undefined),
    industry:        pillFilter.industry        || (industry     !== "all" ? industry     : undefined),
    state_code:      stateCode    !== "all"     ? stateCode    : undefined,
    email_status:    pillFilter.email_status    || (emailStatus  !== "all" ? emailStatus  : undefined),
    api_source:      pillFilter.api_source      || undefined,
    buying_role:     pillFilter.buying_role     || undefined,
    intent_strength: pillFilter.intent_strength || undefined,
  };

  const { leads, total, loading } = useLeads(filter);

  const hasFilter = nlQuery || activePills.length > 0 ||
    seniority !== "all" || industry !== "all" ||
    stateCode !== "all" || emailStatus !== "all";

  // ── Handlers ───────────────────────────────────────────────────────────────

  const handleInput = useCallback((val: string) => {
    setInputValue(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!val.trim()) { setNlQuery(""); return; }
    setIsThinking(true);
    debounceRef.current = setTimeout(() => {
      setNlQuery(val.trim());
      setIsThinking(false);
      setPage(1);
    }, 500);
  }, []);

  const togglePill = (idx: number) => {
    setActivePills(prev =>
      prev.includes(idx) ? prev.filter(i => i !== idx) : [...prev, idx]
    );
    setPage(1);
  };

  const clearAll = () => {
    setInputValue(""); setNlQuery(""); setActivePills([]);
    setSeniority("all"); setIndustry("all");
    setStateCode("all"); setEmailStatus("all");
    setPage(1);
  };

  const totalPages = Math.ceil(total / 50);

  return (
    <div className="flex flex-col h-full space-y-3">

      {/* ── Control Console (Elevated Card) ────────────────────── */}
      <div className="bg-card rounded-xl border border-border/80 shadow-xs p-3 space-y-2.5">
        {/* ── Primary toolbar ─────────────────────────────────────── */}
        <div className="flex items-center gap-2 flex-wrap">

          {/* Search input */}
          <div className="relative flex-1 min-w-[240px] max-w-md">
            {isThinking
              ? <Loader2 className="absolute left-2.5 top-2 w-3.5 h-3.5 text-muted-foreground animate-spin" />
              : <Search   className="absolute left-2.5 top-2 w-3.5 h-3.5 text-muted-foreground" />
            }
            <Input
              value={inputValue}
              onChange={e => handleInput(e.target.value)}
              placeholder="Search or ask in plain English..."
              className="pl-8 h-8 text-[12px] bg-muted/40 border-border focus:bg-background focus:ring-1 focus:ring-ring"
            />
            {inputValue && (
              <button
                onClick={() => { setInputValue(""); setNlQuery(""); }}
                className="absolute right-2 top-2 text-muted-foreground hover:text-foreground"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {/* Filter toggle */}
          <Button
            variant="outline"
            size="sm"
            className={`h-8 text-[12px] gap-1.5 ${showFilters ? "bg-muted font-medium" : ""}`}
            onClick={() => setShowFilters(s => !s)}
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
            Filters
            {hasFilter && (
              <span className="w-1.5 h-1.5 rounded-full bg-amber-500 flex-shrink-0" />
            )}
          </Button>

          {/* Clear */}
          {hasFilter && (
            <Button variant="ghost" size="sm" className="h-8 text-[12px] text-muted-foreground hover:text-foreground" onClick={clearAll}>
              <X className="w-3 h-3 mr-1" /> Clear
            </Button>
          )}

          {/* Spacer */}
          <div className="flex-1" />

          {/* Record count */}
          <span className="text-[12px] font-mono tabnum text-muted-foreground whitespace-nowrap bg-muted/40 px-2.5 py-1 rounded border border-border/60">
            {loading ? "..." : `${total.toLocaleString("en-US")} records`}
          </span>

          {/* View Toggle */}
          <div className="flex items-center border border-border rounded-md p-0.5 bg-muted/30">
            <Button
              variant={viewMode === "table" ? "secondary" : "ghost"}
              size="sm"
              className="h-7 px-2 text-[12px] gap-1"
              onClick={() => setViewMode("table")}
            >
              <TableIcon className="w-3.5 h-3.5" /> Table
            </Button>
            <Button
              variant={viewMode === "map" ? "secondary" : "ghost"}
              size="sm"
              className="h-7 px-2 text-[12px] gap-1"
              onClick={() => setViewMode("map")}
            >
              <MapPin className="w-3.5 h-3.5" /> Map
            </Button>
          </div>

          {/* Export */}
          <Button
            variant="outline"
            size="sm"
            className="h-8 text-[12px] gap-1.5"
            onClick={() =>
              api.download(
                `/export/leads/csv?table=${table}`,
                `${table}-${new Date().toISOString().slice(0, 10)}.csv`
              )
            }
          >
            <Download className="w-3.5 h-3.5" /> Export
          </Button>
        </div>

        {/* ── Expanded filter row ──────────────────────────────────── */}
        <AnimatePresence>
          {showFilters && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="overflow-hidden pt-2 border-t border-border/60"
            >
              <div className="flex flex-wrap items-center gap-2 py-1">
                <FilterSelect label="Seniority" value={seniority} onValueChange={v => { setSeniority(v); setPage(1); }}>
                  <SelectItem value="all">All</SelectItem>
                  <SelectItem value="C_SUITE">C-Suite</SelectItem>
                  <SelectItem value="VP">VP</SelectItem>
                  <SelectItem value="DIRECTOR">Director</SelectItem>
                  <SelectItem value="MANAGER">Manager</SelectItem>
                  <SelectItem value="FOUNDER">Founder</SelectItem>
                </FilterSelect>

                <FilterSelect label="Industry" value={industry} onValueChange={v => { setIndustry(v); setPage(1); }}>
                  <SelectItem value="all">All</SelectItem>
                  <SelectItem value="Healthcare">Healthcare</SelectItem>
                  <SelectItem value="Banking and Finance">Banking</SelectItem>
                  <SelectItem value="Computer Software">Technology</SelectItem>
                  <SelectItem value="Federal Contractor">Federal</SelectItem>
                  <SelectItem value="Nonprofits and Associations">Nonprofits</SelectItem>
                  {table === "mexico_leads" && (
                    <SelectItem value="Industrial Manufacturing & Transformation">Manufacturing</SelectItem>
                  )}
                </FilterSelect>

                <FilterSelect label="State" value={stateCode} onValueChange={v => { setStateCode(v); setPage(1); }}>
                  <SelectItem value="all">All</SelectItem>
                  {["CA","TX","NY","FL","IL","PA","OH","GA","WA","AZ","NC","MA"].map(s => (
                    <SelectItem key={s} value={s}>{s}</SelectItem>
                  ))}
                </FilterSelect>

                <FilterSelect label="Email" value={emailStatus} onValueChange={v => { setEmailStatus(v); setPage(1); }}>
                  <SelectItem value="all">All</SelectItem>
                  <SelectItem value="VERIFIED">Verified</SelectItem>
                  <SelectItem value="VALID">Valid</SelectItem>
                  <SelectItem value="GUESSED">Guessed</SelectItem>
                  <SelectItem value="MISSING">Missing</SelectItem>
                </FilterSelect>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── Quick pill row ───────────────────────────────────────── */}
        <div className="flex items-center gap-1.5 pt-2 border-t border-border/60 overflow-x-auto scrollbar-none flex-nowrap sm:flex-wrap">
          <span className="text-[11px] uppercase tracking-widest text-muted-foreground font-semibold flex-shrink-0 pr-1">
            Quick
          </span>
          {PILLS.map((pill, idx) => {
            const active = activePills.includes(idx);
            return (
              <button
                key={idx}
                onClick={() => togglePill(idx)}
                className={`
                  flex-shrink-0 px-2.5 py-1 rounded text-[11px] font-medium border transition-all
                  ${active
                    ? "bg-foreground text-background border-foreground shadow-2xs font-semibold"
                    : "bg-muted/30 text-muted-foreground border-border hover:border-foreground/40 hover:text-foreground hover:bg-muted/60"
                  }
                `}
              >
                {pill.label}
              </button>
            );
          })}

          {/* AI example queries */}
          <span className="text-[11px] uppercase tracking-widest text-muted-foreground font-semibold flex-shrink-0 pl-3 pr-1">
            AI
          </span>
          {AI_EXAMPLES.map(q => (
            <button
              key={q}
              onClick={() => { setInputValue(q); setNlQuery(q); setPage(1); }}
              className="flex-shrink-0 px-2.5 py-1 rounded text-[11px] text-muted-foreground border border-dashed border-border hover:border-foreground/40 hover:text-foreground bg-muted/20 hover:bg-muted/50 transition-all"
            >
              {q}
            </button>
          ))}
        </div>

        {/* ── Active filter tags ───────────────────────────────────── */}
        <AnimatePresence>
          {nlQuery && (
            <motion.div
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="flex items-center gap-2 pt-2 border-t border-border/60"
            >
              <span className="text-[11px] text-muted-foreground uppercase tracking-wider font-semibold">Query</span>
              <span className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-md bg-muted border border-border text-[12px] font-medium">
                {nlQuery}
                <button onClick={() => { setNlQuery(""); setInputValue(""); }}>
                  <X className="w-3 h-3 text-muted-foreground hover:text-foreground" />
                </button>
              </span>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* ── Table or Map View Card ─────────────────────────────────── */}
      <div className="flex-1 bg-card rounded-xl border border-border/80 shadow-xs overflow-hidden flex flex-col min-h-0">
        {viewMode === "table" ? (
          <div className="flex-1 overflow-x-auto overflow-y-visible scrollbar-enterprise">
            <LeadsTable leads={leads} loading={loading} table={table} />
          </div>
        ) : (
          <div className="flex-1 overflow-hidden min-h-[500px]">
            <LeadsMap leads={leads} className="h-full w-full min-h-[500px]" />
          </div>
        )}
      </div>

      {/* ── Pagination ──────────────────────────────────────────── */}
      {total > 50 && (
        <div className="flex items-center justify-between pt-3 border-t border-border mt-1">
          <span className="text-[12px] font-mono text-muted-foreground tabnum">
            Page {page} / {totalPages.toLocaleString("en-US")}
            <span className="ml-2 text-muted-foreground/50">
              ({((page - 1) * 50 + 1).toLocaleString("en-US")}–{Math.min(page * 50, total).toLocaleString("en-US")} of {total.toLocaleString("en-US")})
            </span>
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="outline" size="sm"
              className="h-7 w-7 p-0"
              disabled={page === 1}
              onClick={() => setPage(p => p - 1)}
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </Button>
            {/* Page numbers */}
            {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
              const p = Math.max(1, Math.min(page - 2, totalPages - 4)) + i;
              return (
                <Button
                  key={p}
                  variant={p === page ? "default" : "outline"}
                  size="sm"
                  className="h-7 w-7 p-0 text-[12px] font-mono"
                  onClick={() => setPage(p)}
                >
                  {p}
                </Button>
              );
            })}
            <Button
              variant="outline" size="sm"
              className="h-7 w-7 p-0"
              disabled={page >= totalPages}
              onClick={() => setPage(p => p + 1)}
            >
              <ChevronRight className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
