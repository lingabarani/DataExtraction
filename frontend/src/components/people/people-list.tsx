"use client";

import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Search,
  X,
  Download,
  ChevronLeft,
  ChevronRight,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { useLeads } from "@/hooks/use-leads";
import { PeopleTable } from "./people-table";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const SENIORITY_PILLS = [
  { label: "All Seniority", value: "all" },
  { label: "C-Suite", value: "C_SUITE" },
  { label: "VP", value: "VP" },
  { label: "Director", value: "DIRECTOR" },
  { label: "Founder", value: "FOUNDER" },
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

  const currentTable: "us_leads" | "mexico_leads" =
    countryTab === "mexico" ? "mexico_leads" : "us_leads";

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
    <div className="flex flex-col gap-6">
      {/* Search & Filter Toolbar */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 rounded-2xl border border-border/80 bg-card p-4 shadow-card">
        <form onSubmit={handleSearchSubmit} className="relative flex-1 max-w-lg">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
          <Input
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Search full name, job title, company, or email..."
            className="h-11 rounded-xl pl-10 pr-9 text-sm bg-muted/35"
          />
          {inputValue && (
            <button
              type="button"
              onClick={handleClearSearch}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              aria-label="Clear search"
            >
              <X className="size-4" />
            </button>
          )}
        </form>

        {/* Country Tabs (Dynamic — No Hardcoded Counts) */}
        <div className="inline-flex items-center gap-1 rounded-xl border border-border bg-muted/50 p-1 self-start lg:self-auto">
          {[
            { id: "all" as const, label: "All Leads" },
            { id: "us" as const, label: "United States" },
            { id: "mexico" as const, label: "Mexico" },
          ].map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => handleCountryToggle(tab.id)}
              className={cn(
                "rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
                countryTab === tab.id
                  ? "bg-card text-foreground shadow-sm font-semibold"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2.5">
          <Select
            value={emailStatus}
            onValueChange={(val) => {
              setEmailStatus(val);
              setPage(1);
            }}
          >
            <SelectTrigger className="h-10 rounded-xl text-xs min-w-[155px]">
              <SelectValue placeholder="Email Status" />
            </SelectTrigger>
            <SelectContent className="rounded-xl">
              <SelectItem value="all" className="text-xs">All Deliverability</SelectItem>
              <SelectItem value="VERIFIED" className="text-xs">Verified Deliverable</SelectItem>
              <SelectItem value="MX_CONFIRMED" className="text-xs">MX Confirmed</SelectItem>
            </SelectContent>
          </Select>

          <Button
            variant="outline"
            size="icon"
            onClick={() => refresh()}
            className="size-10 rounded-xl"
            aria-label="Refresh leads"
          >
            <RefreshCw className={`size-4 ${loading ? "animate-spin text-primary" : ""}`} />
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={handleExport}
            disabled={isExporting}
            className="h-10 rounded-xl px-4 gap-2 text-xs font-medium"
          >
            {isExporting ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Download className="size-4" />
            )}
            <span>Export CSV</span>
          </Button>
        </div>
      </div>

      {/* Seniority Pills */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-none">
        <span className="text-meta text-muted-foreground mr-1">Seniority:</span>
        {SENIORITY_PILLS.map((pill) => (
          <button
            key={pill.value}
            type="button"
            onClick={() => {
              setSeniority(pill.value);
              setPage(1);
            }}
            className={cn(
              "rounded-xl px-3.5 py-1.5 text-xs font-medium transition-colors",
              seniority === pill.value
                ? "bg-primary text-primary-foreground font-semibold shadow-sm"
                : "bg-muted/60 text-muted-foreground hover:bg-muted hover:text-foreground border border-border/60"
            )}
          >
            {pill.label}
          </button>
        ))}
      </div>

      {/* Table Container */}
      <div className="rounded-2xl border border-border/80 bg-card overflow-hidden shadow-card">
        <div className="overflow-x-auto scrollbar-enterprise">
          <PeopleTable people={people} loading={loading} table={currentTable} />
        </div>

        {/* Pagination Footer */}
        <div className="flex items-center justify-between px-5 py-4 border-t border-border/80 bg-muted/20 text-xs text-muted-foreground">
          <span>
            Showing{" "}
            <strong className="font-semibold text-foreground tabular-nums">
              {total > 0 ? (page - 1) * limit + 1 : 0}
            </strong>
            –
            <strong className="font-semibold text-foreground tabular-nums">
              {Math.min(page * limit, total)}
            </strong>{" "}
            of{" "}
            <strong className="font-semibold text-foreground tabular-nums">
              {total.toLocaleString("en-US")}
            </strong>{" "}
            decision-makers
          </span>

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="icon"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1 || loading}
              className="size-8 rounded-lg"
              aria-label="Previous page"
            >
              <ChevronLeft className="size-4" />
            </Button>
            <span className="px-2 font-mono text-xs font-medium text-foreground tabular-nums">
              {page} / {totalPages}
            </span>
            <Button
              variant="outline"
              size="icon"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages || loading}
              className="size-8 rounded-lg"
              aria-label="Next page"
            >
              <ChevronRight className="size-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
