"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Play, Layers, Globe, Database, Sparkles, Check } from "lucide-react";
import { StartScrapingPayload } from "../types";
import { cn } from "@/lib/utils";

interface StartScrapingModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (payload: StartScrapingPayload) => Promise<void>;
  isSubmitting: boolean;
}

const DATA_COUNT_OPTIONS = [100, 500, 1000, 5000, 10000, 50000, 100000];
const COUNTRY_OPTIONS = [
  { id: "US", label: "United States", flag: "🇺🇸" },
  { id: "Mexico", label: "Mexico", flag: "🇲🇽" },
  { id: "Canada", label: "Canada", flag: "🇨🇦" },
  { id: "Global", label: "Global Cross-Border", flag: "🌐" },
];

export function StartScrapingModal({
  open,
  onOpenChange,
  onSubmit,
  isSubmitting,
}: StartScrapingModalProps) {
  const [dataCount, setDataCount] = useState<number>(5000);
  const [selectedCountries, setSelectedCountries] = useState<string[]>(["US"]);
  const [sources, setSources] = useState({
    registry_sources: true,
    google_maps: true,
    openstreetmap: true,
  });
  const [executionMode, setExecutionMode] = useState<"INCREMENTAL" | "FULL_REFRESH">("INCREMENTAL");

  const toggleCountry = (code: string) => {
    if (code === "Global") {
      setSelectedCountries(["Global"]);
      return;
    }
    const filtered = selectedCountries.filter((c) => c !== "Global");
    if (filtered.includes(code)) {
      if (filtered.length > 1) {
        setSelectedCountries(filtered.filter((c) => c !== code));
      }
    } else {
      setSelectedCountries([...filtered, code]);
    }
  };

  const handleStart = async () => {
    await onSubmit({
      data_count: dataCount,
      countries: selectedCountries,
      sources,
      execution_mode: executionMode,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl border-border/80 bg-background/95 backdrop-blur-md shadow-2xl p-6 sm:p-7">
        <DialogHeader className="space-y-1.5">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/10 text-primary border border-primary/20">
              <Sparkles className="h-4 w-4" />
            </div>
            <DialogTitle className="text-lg font-semibold tracking-tight">
              Start Master Orchestration Workflow
            </DialogTitle>
          </div>
          <DialogDescription className="text-xs text-muted-foreground">
            Launch the autonomous 8-stage pipeline across Harvesters, Identity Resolution, Email Enrichment, Executive Discovery, and Promotion Gate.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5 py-2">
          {/* Section 1: Data Count */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Data Extraction Count
              </label>
              <span className="font-mono text-xs font-bold text-primary">
                {dataCount.toLocaleString()} targets
              </span>
            </div>
            <div className="grid grid-cols-4 sm:grid-cols-7 gap-1.5">
              {DATA_COUNT_OPTIONS.map((count) => {
                const isSelected = dataCount === count;
                return (
                  <button
                    key={count}
                    type="button"
                    onClick={() => setDataCount(count)}
                    className={cn(
                      "flex flex-col items-center justify-center rounded-md border py-2 px-1 text-xs font-mono transition-all",
                      isSelected
                        ? "border-primary bg-primary/10 text-primary font-bold shadow-xs"
                        : "border-border/60 bg-card/60 text-muted-foreground hover:bg-muted hover:text-foreground"
                    )}
                  >
                    <span>{count >= 1000 ? `${count / 1000}k` : count}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Section 2: Countries */}
          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Geographic Scope
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {COUNTRY_OPTIONS.map((c) => {
                const isSelected = selectedCountries.includes(c.id);
                return (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => toggleCountry(c.id)}
                    className={cn(
                      "flex items-center justify-between rounded-md border px-3 py-2 text-xs transition-all",
                      isSelected
                        ? "border-primary/80 bg-primary/10 text-foreground font-medium shadow-xs"
                        : "border-border/60 bg-card/60 text-muted-foreground hover:bg-muted hover:text-foreground"
                    )}
                  >
                    <span className="flex items-center gap-1.5">
                      <span>{c.flag}</span>
                      <span>{c.label}</span>
                    </span>
                    {isSelected && <Check className="h-3.5 w-3.5 text-primary flex-shrink-0" />}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Section 3: Sources */}
          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Harvester Ingestion Sources
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              <label
                className={cn(
                  "flex items-center gap-2.5 rounded-md border p-2.5 text-xs cursor-pointer transition-all",
                  sources.registry_sources
                    ? "border-emerald-500/50 bg-emerald-500/10 text-foreground font-medium"
                    : "border-border/60 bg-card/60 text-muted-foreground hover:bg-muted"
                )}
              >
                <input
                  type="checkbox"
                  checked={sources.registry_sources}
                  onChange={(e) =>
                    setSources((prev) => ({ ...prev, registry_sources: e.target.checked }))
                  }
                  className="rounded border-border text-primary focus:ring-0"
                />
                <Database className="h-3.5 w-3.5 text-emerald-500" />
                <span>Registry Sources</span>
              </label>

              <label
                className={cn(
                  "flex items-center gap-2.5 rounded-md border p-2.5 text-xs cursor-pointer transition-all",
                  sources.google_maps
                    ? "border-blue-500/50 bg-blue-500/10 text-foreground font-medium"
                    : "border-border/60 bg-card/60 text-muted-foreground hover:bg-muted"
                )}
              >
                <input
                  type="checkbox"
                  checked={sources.google_maps}
                  onChange={(e) =>
                    setSources((prev) => ({ ...prev, google_maps: e.target.checked }))
                  }
                  className="rounded border-border text-primary focus:ring-0"
                />
                <Globe className="h-3.5 w-3.5 text-blue-500" />
                <span>Google Maps</span>
              </label>

              <label
                className={cn(
                  "flex items-center gap-2.5 rounded-md border p-2.5 text-xs cursor-pointer transition-all",
                  sources.openstreetmap
                    ? "border-purple-500/50 bg-purple-500/10 text-foreground font-medium"
                    : "border-border/60 bg-card/60 text-muted-foreground hover:bg-muted"
                )}
              >
                <input
                  type="checkbox"
                  checked={sources.openstreetmap}
                  onChange={(e) =>
                    setSources((prev) => ({ ...prev, openstreetmap: e.target.checked }))
                  }
                  className="rounded border-border text-primary focus:ring-0"
                />
                <Layers className="h-3.5 w-3.5 text-purple-500" />
                <span>OpenStreetMap</span>
              </label>
            </div>
          </div>

          {/* Section 4: Execution Mode */}
          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Execution Mode
            </label>
            <div className="grid grid-cols-2 gap-2.5">
              <button
                type="button"
                onClick={() => setExecutionMode("INCREMENTAL")}
                className={cn(
                  "flex flex-col items-start rounded-md border p-3 text-left transition-all",
                  executionMode === "INCREMENTAL"
                    ? "border-primary bg-primary/10 text-foreground shadow-xs"
                    : "border-border/60 bg-card/60 text-muted-foreground hover:bg-muted"
                )}
              >
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-xs">Incremental Sync</span>
                  <Badge variant="outline" className="text-[9px] py-0 font-mono">
                    FAST
                  </Badge>
                </div>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  Processes new changes; respects 30d/90d freshness SLA windows.
                </p>
              </button>

              <button
                type="button"
                onClick={() => setExecutionMode("FULL_REFRESH")}
                className={cn(
                  "flex flex-col items-start rounded-md border p-3 text-left transition-all",
                  executionMode === "FULL_REFRESH"
                    ? "border-amber-500/80 bg-amber-500/10 text-foreground shadow-xs"
                    : "border-border/60 bg-card/60 text-muted-foreground hover:bg-muted"
                )}
              >
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-xs text-amber-500 dark:text-amber-400">
                    Full Refresh
                  </span>
                  <Badge variant="outline" className="text-[9px] py-0 font-mono border-amber-500/30 text-amber-500">
                    DEEP SCAN
                  </Badge>
                </div>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  Forces end-to-end re-harvesting and re-validates all records.
                </p>
              </button>
            </div>
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-0 pt-2 border-t border-border/60">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isSubmitting}
            className="text-xs font-mono h-9"
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={handleStart}
            disabled={isSubmitting}
            className="gap-2 text-xs font-medium h-9 bg-primary hover:bg-primary/90 text-primary-foreground font-mono"
          >
            <Play className="h-3.5 w-3.5 fill-current" />
            {isSubmitting ? "Dispatching to Temporal..." : "Start Workflow"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

