"use client";

import { useState, useCallback, useRef } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem,
  SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Search, X, Download, ChevronLeft, ChevronRight,
  SlidersHorizontal, Loader2, Building2, Globe, RefreshCw,
} from "lucide-react";
import { useLeads } from "@/hooks/use-leads";
import { CompaniesTable } from "./companies-table";
import { api } from "@/lib/api";
import { toast } from "sonner";

const INDUSTRIES = [
  "All",
  "Technology",
  "Healthcare",
  "Finance",
  "Manufacturing",
  "Retail",
  "Real Estate",
  "Professional Services",
  "Public Corporation",
];

export function CompaniesList() {
  const [q, setQ] = useState("");
  const [inputValue, setInputValue] = useState("");
  const [selectedCountry, setSelectedCountry] = useState<string>("all");
  const [selectedIndustry, setSelectedIndustry] = useState<string>("all");
  const [minScore, setMinScore] = useState<number | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [isExporting, setIsExporting] = useState(false);
  const limit = 25;

  const countryParam = selectedCountry === "all" ? undefined : selectedCountry;
  const industryParam = selectedIndustry === "all" ? undefined : selectedIndustry;

  const { leads: companies, total, loading, refresh } = useLeads({
    table: "master_organizations",
    q: q || undefined,
    country: countryParam,
    industry: industryParam,
    min_score: minScore,
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

  const handleCountryToggle = (country: string) => {
    setSelectedCountry(country);
    setPage(1);
  };

  const handleExport = async () => {
    try {
      setIsExporting(true);
      toast.info("Preparing corporate registry export...");
      await api.download(
        `/export/leads/csv?table=master_organizations`,
        `corporate-registry-${new Date().toISOString().slice(0, 10)}.csv`
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
      {/* ── Search & Filter Bar ─────────────────────────────────────────── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 bg-card border border-border p-3 rounded-lg shadow-2xs">
        {/* Search input */}
        <form onSubmit={handleSearchSubmit} className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Search company name, domain, EIN, industry..."
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
              selectedCountry === "all"
                ? "bg-background text-foreground shadow-xs font-semibold"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            All <span className="text-[10px] opacity-70 font-mono">213K</span>
          </button>
          <button
            type="button"
            onClick={() => handleCountryToggle("United States")}
            className={`px-2.5 py-1 text-[11.5px] font-medium rounded transition-all ${
              selectedCountry === "United States"
                ? "bg-background text-foreground shadow-xs font-semibold"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            United States <span className="text-[10px] opacity-70 font-mono">208K</span>
          </button>
          <button
            type="button"
            onClick={() => handleCountryToggle("Mexico")}
            className={`px-2.5 py-1 text-[11.5px] font-medium rounded transition-all ${
              selectedCountry === "Mexico"
                ? "bg-background text-foreground shadow-xs font-semibold"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            Mexico <span className="text-[10px] opacity-70 font-mono">5K</span>
          </button>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          {/* Industry dropdown */}
          <Select value={selectedIndustry} onValueChange={(val) => { setSelectedIndustry(val); setPage(1); }}>
            <SelectTrigger className="h-9 text-[12px] min-w-[130px]">
              <SelectValue placeholder="Industry" />
            </SelectTrigger>
            <SelectContent>
              {INDUSTRIES.map((ind) => (
                <SelectItem key={ind} value={ind} className="text-[12px]">
                  {ind}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Refresh Button */}
          <Button
            variant="outline"
            size="sm"
            onClick={() => refresh()}
            className="h-9 px-2.5 text-xs text-muted-foreground hover:text-foreground"
            title="Refresh organizations"
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

      {/* ── Table Container ────────────────────────────────────────────── */}
      <div className="rounded-lg border border-border bg-card overflow-hidden shadow-2xs">
        <div className="overflow-x-auto">
          <CompaniesTable companies={companies} loading={loading} />
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
              organizations
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
