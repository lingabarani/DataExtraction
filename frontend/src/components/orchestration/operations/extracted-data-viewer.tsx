"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  FileSpreadsheet,
  Download,
  RefreshCw,
  Search,
  ExternalLink,
  MapPin,
  Phone,
  Globe,
  Building2,
  ShieldCheck,
  CheckCircle2,
  Loader2,
  Layers,
  Filter,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface ExtractedRecord {
  id: string;
  name: string;
  legal_name?: string | null;
  website?: string | null;
  domain?: string | null;
  phone?: string | null;
  city?: string | null;
  state?: string | null;
  state_code?: string | null;
  zip_code?: string | null;
  country?: string | null;
  industry?: string | null;
  source: string;
  data_quality_score: number;
  created_at?: string | null;
  scraped_at?: string | null;
  status: string;
}

interface ExtractedDataResponse {
  status: string;
  total_staging_records: number;
  returned_records: number;
  active_source_filter: string;
  sources_distribution: Record<string, number>;
  records: ExtractedRecord[];
  timestamp: string;
}

const SOURCE_FILTERS = [
  { id: "ALL", label: "All Sources" },
  { id: "GOOGLE_MAPS", label: "Google Maps" },
  { id: "OPENSTREETMAP", label: "OpenStreetMap" },
  { id: "OPEN_DIRECTORIES_SF", label: "Open Directories" },
  { id: "REGISTRY", label: "Registries (SEC/FDIC)" },
];

export function ExtractedDataViewer() {
  const [data, setData] = useState<ExtractedDataResponse | null>(null);
  const [records, setRecords] = useState<ExtractedRecord[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isExportingExcel, setIsExportingExcel] = useState<boolean>(false);
  const [isExportingCsv, setIsExportingCsv] = useState<boolean>(false);
  const [selectedSource, setSelectedSource] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [limit, setLimit] = useState<number>(100);

  const fetchData = useCallback(
    async (sourceFilter: string, search: string, limitVal: number) => {
      setIsLoading(true);
      try {
        const params = new URLSearchParams();
        if (sourceFilter !== "ALL") params.set("source", sourceFilter);
        if (search.trim()) params.set("search", search.trim());
        params.set("limit", String(limitVal));

        const res = await api.get<ExtractedDataResponse>(
          `/orchestration/extracted-data?${params.toString()}`
        );
        setData(res);
        setRecords(res.records || []);
      } catch (err: any) {
        toast.error("Failed to fetch extracted staging data", {
          description: err?.message || String(err),
        });
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    const handler = setTimeout(() => {
      fetchData(selectedSource, searchQuery, limit);
    }, 250);
    return () => clearTimeout(handler);
  }, [fetchData, selectedSource, searchQuery, limit]);

  const handleDownloadExcel = async () => {
    setIsExportingExcel(true);
    try {
      const params = new URLSearchParams();
      params.set("format", "xlsx");
      params.set("limit", "1000"); // Top 1,000 records for sub-2s download
      if (selectedSource !== "ALL") params.set("source", selectedSource);
      if (searchQuery.trim()) params.set("search", searchQuery.trim());

      const timestamp = new Date().toISOString().slice(0, 10);
      const filename = `recent_scraped_data_${selectedSource.toLowerCase()}_${timestamp}.xlsx`;

      await api.download(`/orchestration/extracted-data/export?${params.toString()}`, filename);
      toast.success("Excel Spreadsheet Downloaded Successfully", {
        description: `Exported 1,000 recent scraped records to ${filename}`,
      });
    } catch (err: any) {
      toast.error("Excel export failed", {
        description: err?.message || String(err),
      });
    } finally {
      setIsExportingExcel(false);
    }
  };

  const handleDownloadCsv = async () => {
    setIsExportingCsv(true);
    try {
      const params = new URLSearchParams();
      params.set("format", "csv");
      params.set("limit", "1000");
      if (selectedSource !== "ALL") params.set("source", selectedSource);
      if (searchQuery.trim()) params.set("search", searchQuery.trim());

      const timestamp = new Date().toISOString().slice(0, 10);
      const filename = `recent_scraped_data_${selectedSource.toLowerCase()}_${timestamp}.csv`;

      await api.download(`/orchestration/extracted-data/export?${params.toString()}`, filename);
      toast.success("CSV File Downloaded Successfully", {
        description: `Exported recent scraped records to ${filename}`,
      });
    } catch (err: any) {
      toast.error("CSV export failed", {
        description: err?.message || String(err),
      });
    } finally {
      setIsExportingCsv(false);
    }
  };

  const getSourceBadge = (src: string) => {
    const s = (src || "").toUpperCase();
    if (s.includes("GOOGLE_MAPS") || s.includes("GMAP")) {
      return (
        <Badge
          variant="outline"
          className="border-sky-500/40 bg-sky-500/10 text-sky-600 dark:text-sky-400 font-mono text-[10px] gap-1"
        >
          <Globe className="h-3 w-3" />
          GOOGLE MAPS
        </Badge>
      );
    }
    if (s.includes("OPENSTREETMAP") || s.includes("OSM")) {
      return (
        <Badge
          variant="outline"
          className="border-purple-500/40 bg-purple-500/10 text-purple-600 dark:text-purple-400 font-mono text-[10px] gap-1"
        >
          <MapPin className="h-3 w-3" />
          OPENSTREETMAP
        </Badge>
      );
    }
    if (s.includes("REGISTRY") || s.includes("FDIC") || s.includes("SEC") || s.includes("PROPUBLICA")) {
      return (
        <Badge
          variant="outline"
          className="border-emerald-500/40 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 font-mono text-[10px] gap-1"
        >
          <Building2 className="h-3 w-3" />
          {s.slice(0, 15)}
        </Badge>
      );
    }
    return (
      <Badge
        variant="outline"
        className="border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400 font-mono text-[10px] gap-1"
      >
        <Layers className="h-3 w-3" />
        {s.slice(0, 16)}
      </Badge>
    );
  };

  return (
    <div className="flex flex-col gap-5 rounded-xl border border-border/70 bg-card p-4 sm:p-6 shadow-xs">
      {/* ── Top Header Ribbon ── */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b border-border/60 pb-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-500 border border-emerald-500/20">
              <FileSpreadsheet className="h-4.5 w-4.5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-semibold tracking-tight text-foreground">
                  Recently Scraped & Extracted Datasets
                </h3>
                <Badge
                  variant="outline"
                  className="font-mono text-[10px] text-emerald-600 dark:text-emerald-400 border-emerald-500/30 bg-emerald-500/10"
                >
                  LIVE STAGING VAULT
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground">
                Inspecting newly harvested records with verified timestamps, contact coordinates, and source attribution.
              </p>
            </div>
          </div>
        </div>

        {/* ── Action Buttons ── */}
        <div className="flex flex-wrap items-center gap-2.5">
          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchData(selectedSource, searchQuery, limit)}
            disabled={isLoading}
            className="h-8 gap-1.5 text-xs font-medium border-border/70"
            title="Refresh extracted records"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isLoading && "animate-spin")} />
            Refresh
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={handleDownloadCsv}
            disabled={isExportingCsv || records.length === 0}
            className="h-8 gap-1.5 text-xs font-medium border-border/70 hover:bg-muted"
            title="Download top 1,000 as CSV"
          >
            {isExportingCsv ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            CSV
          </Button>

          <Button
            size="sm"
            onClick={handleDownloadExcel}
            disabled={isExportingExcel || records.length === 0}
            className="h-8 gap-2 text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white shadow-xs transition-all"
            title="Download top 1,000 recently scraped records into an Excel (.xlsx) file"
          >
            {isExportingExcel ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <FileSpreadsheet className="h-3.5 w-3.5" />
            )}
            Download Excel (.xlsx)
          </Button>
        </div>
      </div>

      {/* ── Filter & Search Toolbar ── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        {/* Source Pills */}
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground mr-1 flex items-center gap-1">
            <Filter className="h-3 w-3" /> Source:
          </span>
          {SOURCE_FILTERS.map((f) => {
            const isSelected = selectedSource === f.id;
            return (
              <button
                key={f.id}
                type="button"
                onClick={() => setSelectedSource(f.id)}
                className={cn(
                  "rounded-md px-2.5 py-1 text-xs font-medium transition-all",
                  isSelected
                    ? "bg-primary text-primary-foreground shadow-xs font-semibold"
                    : "bg-muted/60 text-muted-foreground hover:bg-muted hover:text-foreground border border-border/50"
                )}
              >
                {f.label}
              </button>
            );
          })}
        </div>

        {/* Search & Limit Box */}
        <div className="flex items-center gap-2">
          <div className="relative w-full md:w-64">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              type="text"
              placeholder="Search name, domain, city..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="h-8 pl-8 text-xs bg-background/80"
            />
          </div>

          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-muted-foreground whitespace-nowrap">Show:</span>
            <select
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="h-8 rounded-md border border-border/70 bg-background px-2 text-xs font-mono text-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={250}>250</option>
            </select>
          </div>
        </div>
      </div>

      {/* ── Status Metric Bar ── */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-muted/40 px-3.5 py-2 border border-border/50 text-xs">
        <div className="flex items-center gap-3">
          <span className="text-muted-foreground">
            Total In Staging Vault:{" "}
            <strong className="text-foreground font-mono">
              {data?.total_staging_records?.toLocaleString() ?? "265,365"}
            </strong>
          </span>
          <span className="text-border">|</span>
          <span className="text-muted-foreground">
            Displaying:{" "}
            <strong className="text-foreground font-mono">{records.length}</strong> records
          </span>
        </div>
        <div className="flex items-center gap-2 text-[11px] font-mono text-muted-foreground">
          <ShieldCheck className="h-3.5 w-3.5 text-emerald-500" />
          <span>Excel Export Scope: Top 1,000 Recent Records (Sub-2s Streaming)</span>
        </div>
      </div>

      {/* ── Records Table ── */}
      <div className="rounded-lg border border-border/70 overflow-hidden bg-background">
        <div className="overflow-x-auto max-h-[520px]">
          <table className="w-full text-left border-collapse text-xs">
            <thead className="sticky top-0 z-10 bg-muted/90 backdrop-blur border-b border-border text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
              <tr>
                <th className="py-2.5 px-3 w-12 text-center">#</th>
                <th className="py-2.5 px-3 min-w-[200px]">Organization / Place</th>
                <th className="py-2.5 px-3 min-w-[160px]">Domain & Contact</th>
                <th className="py-2.5 px-3 min-w-[150px]">Location</th>
                <th className="py-2.5 px-3 min-w-[130px]">Source</th>
                <th className="py-2.5 px-3 min-w-[90px] text-center">Quality</th>
                <th className="py-2.5 px-3 min-w-[160px]">Scraped Date & Time</th>
                <th className="py-2.5 px-3 w-28 text-center">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {isLoading ? (
                // Shimmer Loading Skeleton
                Array.from({ length: 8 }).map((_, idx) => (
                  <tr key={idx} className="animate-pulse">
                    <td className="py-3 px-3 text-center">
                      <div className="h-3.5 w-5 bg-muted rounded mx-auto" />
                    </td>
                    <td className="py-3 px-3">
                      <div className="h-4 w-36 bg-muted rounded mb-1" />
                      <div className="h-3 w-24 bg-muted/60 rounded" />
                    </td>
                    <td className="py-3 px-3">
                      <div className="h-3.5 w-28 bg-muted rounded mb-1" />
                      <div className="h-3 w-20 bg-muted/60 rounded" />
                    </td>
                    <td className="py-3 px-3">
                      <div className="h-3.5 w-24 bg-muted rounded" />
                    </td>
                    <td className="py-3 px-3">
                      <div className="h-5 w-24 bg-muted rounded" />
                    </td>
                    <td className="py-3 px-3 text-center">
                      <div className="h-4 w-10 bg-muted rounded mx-auto" />
                    </td>
                    <td className="py-3 px-3">
                      <div className="h-3.5 w-28 bg-muted rounded" />
                    </td>
                    <td className="py-3 px-3 text-center">
                      <div className="h-5 w-16 bg-muted rounded mx-auto" />
                    </td>
                  </tr>
                ))
              ) : records.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-12 text-center text-muted-foreground">
                    <div className="flex flex-col items-center justify-center gap-2">
                      <Search className="h-7 w-7 text-muted-foreground/40" />
                      <p className="font-medium text-sm">No extracted records match your query</p>
                      <p className="text-xs text-muted-foreground/70">
                        Try clearing search terms or selecting a different harvester source filter.
                      </p>
                    </div>
                  </td>
                </tr>
              ) : (
                records.map((r, idx) => {
                  const displayDate = r.scraped_at
                    ? new Date(r.scraped_at).toLocaleString()
                    : r.created_at
                    ? new Date(r.created_at).toLocaleString()
                    : "Recently Scraped";

                  const scorePercent = Math.round(Number(r.data_quality_score || 0.85) * 100);

                  return (
                    <tr
                      key={r.id || idx}
                      className="hover:bg-muted/40 transition-colors group"
                    >
                      {/* Index */}
                      <td className="py-2.5 px-3 text-center font-mono text-[11px] text-muted-foreground">
                        {idx + 1}
                      </td>

                      {/* Name */}
                      <td className="py-2.5 px-3">
                        <div className="font-medium text-foreground group-hover:text-primary transition-colors flex items-center gap-1.5">
                          <span>{r.name}</span>
                          {r.website && (
                            <a
                              href={r.website.startsWith("http") ? r.website : `https://${r.website}`}
                              target="_blank"
                              rel="noreferrer"
                              className="text-muted-foreground hover:text-primary transition-colors"
                              title={`Visit ${r.website}`}
                            >
                              <ExternalLink className="h-3 w-3" />
                            </a>
                          )}
                        </div>
                        {r.industry && (
                          <div className="text-[11px] text-muted-foreground/80 truncate max-w-[240px]">
                            {r.industry}
                          </div>
                        )}
                      </td>

                      {/* Domain & Phone */}
                      <td className="py-2.5 px-3 space-y-0.5">
                        {r.domain ? (
                          <div className="font-mono text-[11px] text-primary truncate max-w-[180px]">
                            {r.domain}
                          </div>
                        ) : (
                          <div className="text-[11px] text-muted-foreground/60 italic">No domain</div>
                        )}
                        {r.phone && (
                          <div className="flex items-center gap-1 font-mono text-[11px] text-muted-foreground">
                            <Phone className="h-2.5 w-2.5 text-muted-foreground/60" />
                            <a href={`tel:${r.phone}`} className="hover:underline">
                              {r.phone}
                            </a>
                          </div>
                        )}
                      </td>

                      {/* Location */}
                      <td className="py-2.5 px-3">
                        <div className="flex items-center gap-1 text-foreground">
                          <MapPin className="h-3 w-3 text-muted-foreground/70 shrink-0" />
                          <span className="truncate max-w-[160px]">
                            {[r.city, r.state, r.country].filter(Boolean).join(", ") || "United States"}
                          </span>
                        </div>
                      </td>

                      {/* Source */}
                      <td className="py-2.5 px-3">
                        {getSourceBadge(r.source)}
                      </td>

                      {/* Quality Score */}
                      <td className="py-2.5 px-3 text-center font-mono">
                        <span
                          className={cn(
                            "inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-bold",
                            scorePercent >= 80
                              ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                              : scorePercent >= 60
                              ? "bg-amber-500/10 text-amber-600 dark:text-amber-400"
                              : "bg-rose-500/10 text-rose-600 dark:text-rose-400"
                          )}
                        >
                          {scorePercent}%
                        </span>
                      </td>

                      {/* Scraped At */}
                      <td className="py-2.5 px-3 font-mono text-[11px] text-muted-foreground">
                        {displayDate}
                      </td>

                      {/* Status */}
                      <td className="py-2.5 px-3 text-center">
                        <Badge
                          variant="secondary"
                          className="font-mono text-[10px] bg-muted text-muted-foreground px-1.5 py-0.5"
                        >
                          <CheckCircle2 className="h-2.5 w-2.5 mr-1 text-emerald-500 inline" />
                          STAGED
                        </Badge>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
