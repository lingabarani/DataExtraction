"use client";

import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem,
  SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Search, X, Download, ChevronLeft, ChevronRight,
  SlidersHorizontal, Loader2, Users, RefreshCw, ShieldCheck,
} from "lucide-react";
import { useLeads } from "@/hooks/use-leads";
import { PeopleTable } from "./people-table";
import { api } from "@/lib/api";
import { toast } from "sonner";

const SENIORITY_PILLS = [
  { label: "All Seniority", value: "all" },
  { label: "C-Suite",       value: "C_SUITE" },
  { label: "VP",            value: "VP" },
  { label: "Director",      value: "DIRECTOR" },
  { label: "Founder",       value: "FOUNDER" },
];

export function PeopleList() {
  const [q, setQ] = useState("");
  const [inputValue, setInputValue] = useState("");
  const [countryTab, setCountryTab] = useState<"all" | "us" | "mexico">("all");
  const [seniority, setSeniority] = useState<string>("all");
  const [emailStatus, setEmailStatus] = useState<string>("all");
  const [page, setPage] = useState(1);
  const [isExporting, setIsExporting] = useState(false);
  const limit = 25;

  const currentTable: "us_leads" | "mexico_leads" = countryTab === "mexico" ? "mexico_leads" : "us_leads";

  const { leads: people, total, loading, refresh } = useLeads({
    table: currentTable,
    q: q || undefined,
    seniority: seniority === "all" ? undefined : seniority,
    email_status: emailStatus === "all" ? undefined : emailStatus,
    page,
    limit,
  });

  const totalPages = Math.max(1, Math.ceil(total / limit));

  const handleSearchSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setQ(inputValue.trim());
    setPage(1);
  };

  const handleClearSearch = () => {
    setInputValue("");
    setQ("");
    setPage(1);
  };

  const handleCountryToggle = (tab: "all" | "us" | "mexico") => {
    setCountryTab(tab);
    setPage(1);
  };

  const handleExport = async () => {
    try {
      setIsExporting(true);
      toast.info("Preparing executive contacts export...");
      await api.download(
        `/export/leads/csv?table=${currentTable}`,
        `executive-leads-${new Date().toISOString().slice(0, 10)}.csv`
      );
      toast.success("Download initiated");
    } catch {
      toast.error("Export failed. Please check connection.");
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* ── Search & Filter Controls ────────────────────────────────────── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 bg-card border border-border p-3 rounded-lg shadow-2xs">
        {/* Search input */}
        <form onSubmit={handleSearchSubmit} className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Search full name, job title, company, or email..."
            className="pl-9 pr-8 h-9 text-[13px] bg-background"
          />
          {inputValue && (
            <button
              type="button"
              onClick={handleClearSearch}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground/50 hover:text-foreground"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </form>

        {/* Quick Country Switcher Tabs */}
        <div className="flex items-center gap-1 bg-muted/60 p-1 rounded-md border border-border/80 self-start md:self-auto">
          <button
            type="button"
            onClick={() => handleCountryToggle("all")}
            className={`px-2.5 py-1 text-[11.5px] font-medium rounded transition-all ${
              countryTab === "all"
                ? "bg-background text-foreground shadow-xs font-semibold"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            All Executive Leads <span className="text-[10px] opacity-70 font-mono">115K</span>
          </button>
          <button
            type="button"
            onClick={() => handleCountryToggle("us")}
            className={`px-2.5 py-1 text-[11.5px] font-medium rounded transition-all ${
              countryTab === "us"
                ? "bg-background text-foreground shadow-xs font-semibold"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            United States <span className="text-[10px] opacity-70 font-mono">65K</span>
          </button>
          <button
            type="button"
            onClick={() => handleCountryToggle("mexico")}
            className={`px-2.5 py-1 text-[11.5px] font-medium rounded transition-all ${
              countryTab === "mexico"
                ? "bg-background text-foreground shadow-xs font-semibold"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            Mexico <span className="text-[10px] opacity-70 font-mono">50K</span>
          </button>
        </div>

        {/* Actions & Filters */}
        <div className="flex items-center gap-2">
          {/* Deliverability Status Filter */}
          <Select value={emailStatus} onValueChange={(val) => { setEmailStatus(val); setPage(1); }}>
            <SelectTrigger className="h-9 text-[12px] min-w-[130px]">
              <SelectValue placeholder="Email Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all" className="text-[12px]">All Deliverability</SelectItem>
              <SelectItem value="VERIFIED" className="text-[12px]">Verified Deliverable</SelectItem>
              <SelectItem value="MX_CONFIRMED" className="text-[12px]">MX Confirmed</SelectItem>
            </SelectContent>
          </Select>

          {/* Refresh Button */}
          <Button
            variant="outline"
            size="sm"
            onClick={() => refresh()}
            className="h-9 px-2.5 text-xs text-muted-foreground hover:text-foreground"
            title="Refresh leads"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          </Button>

          {/* Export CSV Button */}
          <Button
            variant="outline"
            size="sm"
            onClick={handleExport}
            disabled={isExporting}
            className="h-9 gap-1.5 text-xs font-medium"
          >
            {isExporting ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Download className="w-3.5 h-3.5" />
            )}
            <span>Export</span>
          </Button>
        </div>
      </div>

      {/* ── Seniority Quick Filter Pills ─────────────────────────────────── */}
      <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-none">
        <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground mr-1">
          Seniority:
        </span>
        {SENIORITY_PILLS.map((pill) => (
          <button
            key={pill.value}
            type="button"
            onClick={() => { setSeniority(pill.value); setPage(1); }}
            className={`px-2.5 py-1 rounded text-[11.5px] font-medium transition-all ${
              seniority === pill.value
                ? "bg-primary text-primary-foreground font-semibold shadow-xs"
                : "bg-muted/70 text-muted-foreground hover:bg-muted hover:text-foreground border border-border/60"
            }`}
          >
            {pill.label}
          </button>
        ))}
      </div>

      {/* ── Table Container ────────────────────────────────────────────── */}
      <div className="rounded-lg border border-border bg-card overflow-hidden shadow-2xs">
        <div className="overflow-x-auto">
          <PeopleTable people={people} loading={loading} table={currentTable} />
        </div>

        {/* ── Pagination Footer ──────────────────────────────────────────── */}
        <div className="flex items-center justify-between px-4 py-3 border-t border-border bg-muted/20 text-[12.5px] text-muted-foreground">
          <div className="flex items-center gap-2">
            <span>
              Showing{" "}
              <strong className="font-semibold text-foreground tabnum font-mono">
                {total > 0 ? (page - 1) * limit + 1 : 0}
              </strong>
              –
              <strong className="font-semibold text-foreground tabnum font-mono">
                {Math.min(page * limit, total)}
              </strong>{" "}
              of{" "}
              <strong className="font-semibold text-foreground tabnum font-mono">
                {total.toLocaleString("en-US")}
              </strong>{" "}
              decision-makers
            </span>
          </div>

          <div className="flex items-center gap-1.5">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1 || loading}
              className="h-7 w-7 p-0"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </Button>
            <span className="px-2 font-mono text-[11.5px] font-medium text-foreground tabnum">
              {page} / {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages || loading}
              className="h-7 w-7 p-0"
            >
              <ChevronRight className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
