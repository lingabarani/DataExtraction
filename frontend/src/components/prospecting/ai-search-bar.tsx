"use client";

import React, { useState, useEffect } from "react";
import {
  Building2,
  Users,
  Sparkles,
  Search,
  Loader2,
  X,
  ArrowRight,
  Bot,
  Bookmark,
  BookmarkPlus,
  Download,
  RotateCcw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ProspectingMode } from "@/lib/prospecting-api";
import { cn } from "@/lib/utils";
import { toast } from "sonner";

export type SearchProgressStage =
  | "idle"
  | "generating_query"
  | "searching_database"
  | "applying_filters"
  | "rendering";

interface SavedSearchItem {
  id: string;
  label: string;
  query: string;
  mode: ProspectingMode;
}

const SAVED_SEARCHES_KEY = "de_saved_searches_v1";

const DEFAULT_SAVED_SEARCHES: SavedSearchItem[] = [
  { id: "preset-ca-health", label: "CA Healthcare Companies", query: "Healthcare companies in California", mode: "company" },
  { id: "preset-ca-ctos", label: "California CTOs", query: "CTO in California", mode: "people" },
  { id: "preset-tx-homecare", label: "Texas Homecare", query: "Homecare in Texas", mode: "company" },
  { id: "preset-ca-founders", label: "California Founders", query: "Founders in California", mode: "people" },
];

interface AiSearchBarProps {
  mode: ProspectingMode;
  onModeChange: (newMode: ProspectingMode) => void;
  onSearchPrompt: (prompt: string) => Promise<void>;
  isLoading: boolean;
  searchStage?: SearchProgressStage;
  synthesizedQuery?: string;
  aiSummary: string | null;
  onClearSummary: () => void;
  expandedKeywords?: string[];
  onRemoveKeyword?: (kw: string) => void;
  activePills: { category: string; value: string; label: string }[];
  onRemovePill: (category: string, value: string) => void;
  onClearAllPills: () => void;
  onExportCsv?: () => void;
  canExport?: boolean;
}

export function AiSearchBar({
  mode,
  onModeChange,
  onSearchPrompt,
  isLoading,
  searchStage = "idle",
  aiSummary,
  onClearSummary,
  expandedKeywords = [],
  onRemoveKeyword,
  activePills,
  onRemovePill,
  onClearAllPills,
  onExportCsv,
  canExport = false,
}: AiSearchBarProps) {
  const [prompt, setPrompt] = useState("");
  const [savedSearches, setSavedSearches] = useState<SavedSearchItem[]>(DEFAULT_SAVED_SEARCHES);

  useEffect(() => {
    void Promise.resolve().then(() => {
      try {
        const raw = window.localStorage.getItem(SAVED_SEARCHES_KEY);
        if (raw) {
          const parsed = JSON.parse(raw);
          if (Array.isArray(parsed) && parsed.length > 0) {
            setSavedSearches(parsed);
          }
        }
      } catch {
        // Fall back to curated presets
      }
    });
  }, []);

  const persistSavedSearches = (next: SavedSearchItem[]) => {
    setSavedSearches(next);
    try {
      window.localStorage.setItem(SAVED_SEARCHES_KEY, JSON.stringify(next));
    } catch {
      // Ignore storage failures
    }
  };

  const handleSaveCurrentSearch = () => {
    const clean = prompt.trim();
    if (!clean) {
      toast.info("Enter a query in the search bar to save it.");
      return;
    }
    const duplicate = savedSearches.some(
      (s) => s.query.toLowerCase() === clean.toLowerCase() && s.mode === mode
    );
    if (duplicate) {
      toast.info("This search is already saved.");
      return;
    }
    const item: SavedSearchItem = {
      id: `saved-${Date.now()}`,
      label: clean.length > 28 ? `${clean.slice(0, 26)}…` : clean,
      query: clean,
      mode,
    };
    persistSavedSearches([item, ...savedSearches].slice(0, 8));
    toast.success("Search pinned to Saved Searches");
  };

  const handleRemoveSaved = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    persistSavedSearches(savedSearches.filter((s) => s.id !== id));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim() || isLoading) return;
    onSearchPrompt(prompt.trim());
  };

  const handleRunSaved = (item: SavedSearchItem) => {
    if (item.mode !== mode) {
      onModeChange(item.mode);
    }
    setPrompt(item.query);
    onSearchPrompt(item.query);
  };

  const stageProgressMap: Record<SearchProgressStage, { label: string; pct: number }> = {
    idle: { label: "Ready", pct: 0 },
    generating_query: { label: "Interpreting semantic intent...", pct: 25 },
    searching_database: { label: "Querying verified Master Vault...", pct: 60 },
    applying_filters: { label: "Applying firmographic filters...", pct: 85 },
    rendering: { label: "Rendering records...", pct: 100 },
  };

  const currentStage = stageProgressMap[searchStage] || stageProgressMap.searching_database;

  return (
    <section
      aria-label="Enterprise AI Search"
      className="w-full flex flex-col gap-4 rounded-2xl border border-border/80 bg-card p-5 sm:p-6 shadow-card"
    >
      {/* Top Row: Large Search Bar + Mode Toggle */}
      <div className="flex flex-col lg:flex-row items-stretch lg:items-center gap-3">
        {/* Mode Segmented Toggle */}
        <div
          role="radiogroup"
          aria-label="Entity search mode"
          className="inline-flex items-center rounded-xl border border-border bg-muted/50 p-1 shrink-0 self-start lg:self-auto"
        >
          <button
            type="button"
            role="radio"
            aria-checked={mode === "company"}
            onClick={() => onModeChange("company")}
            className={cn(
              "flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors duration-200 active:scale-[0.98]",
              mode === "company"
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Building2 className="size-4" aria-hidden="true" />
            <span>Companies</span>
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={mode === "people"}
            onClick={() => onModeChange("people")}
            className={cn(
              "flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors duration-200 active:scale-[0.98]",
              mode === "people"
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Users className="size-4" aria-hidden="true" />
            <span>Contacts</span>
          </button>
        </div>

        {/* 56px Enterprise Search Input */}
        <form onSubmit={handleSubmit} className="relative flex-1 flex items-center">
          <div className="pointer-events-none absolute left-4 flex items-center gap-2 text-primary">
            <Sparkles className="size-4" aria-hidden="true" />
          </div>
          <input
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder={
              mode === "company"
                ? "Ask AI: e.g. 'Healthcare companies in California' or search domain, industry..."
                : "Ask AI: e.g. 'CTOs in California' or 'Founders with verified email'..."
            }
            disabled={isLoading}
            aria-label="Enterprise AI natural language search"
            className="h-14 w-full rounded-xl border border-input bg-muted/35 pl-11 pr-36 text-sm sm:text-base text-foreground placeholder:text-muted-foreground transition-colors focus:border-primary focus:bg-background focus:outline-none focus:ring-2 focus:ring-primary/20"
          />
          <div className="absolute right-2 flex items-center gap-1.5">
            {prompt && (
              <button
                type="button"
                onClick={() => setPrompt("")}
                className="rounded-lg p-2 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                aria-label="Clear search text"
              >
                <X className="size-4" />
              </button>
            )}
            <Button
              type="submit"
              disabled={isLoading || !prompt.trim()}
              className="h-10 rounded-lg px-4 text-sm font-medium gap-1.5"
            >
              {isLoading ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <>
                  <Search className="size-4" />
                  <span>Search</span>
                  <ArrowRight className="size-3.5 hidden sm:inline" />
                </>
              )}
            </Button>
          </div>
        </form>
      </div>

      {/* Saved Searches & Quick Actions Strip */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="inline-flex items-center gap-1.5 text-meta text-muted-foreground mr-1">
            <Bookmark className="size-3.5" aria-hidden="true" />
            <span>Saved:</span>
          </span>
          {savedSearches.map((item) => (
            <div
              key={item.id}
              onClick={() => handleRunSaved(item)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  handleRunSaved(item);
                }
              }}
              className="group inline-flex items-center gap-1.5 rounded-lg border border-border/80 bg-muted/40 px-2.5 py-1 text-xs font-medium text-foreground cursor-pointer transition-colors hover:border-primary/40 hover:bg-primary/[0.06]"
            >
              <span>{item.label}</span>
              {item.id.startsWith("saved-") && (
                <button
                  type="button"
                  onClick={(e) => handleRemoveSaved(item.id, e)}
                  className="rounded p-0.5 text-muted-foreground hover:text-destructive"
                  aria-label={`Remove saved search ${item.label}`}
                >
                  <X className="size-3" />
                </button>
              )}
            </div>
          ))}
        </div>

        {/* Quick Actions */}
        <div className="flex items-center gap-2 shrink-0">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={handleSaveCurrentSearch}
            className="h-8 rounded-lg px-2.5 text-xs text-muted-foreground hover:text-foreground gap-1.5"
          >
            <BookmarkPlus className="size-3.5" />
            <span>Save Search</span>
          </Button>
          {onExportCsv && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onExportCsv}
              disabled={!canExport}
              className="h-8 rounded-lg px-3 text-xs gap-1.5"
            >
              <Download className="size-3.5" />
              <span>Export CSV</span>
            </Button>
          )}
          {activePills.length > 0 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onClearAllPills}
              className="h-8 rounded-lg px-2.5 text-xs text-muted-foreground hover:text-destructive gap-1.5"
            >
              <RotateCcw className="size-3.5" />
              <span>Reset</span>
            </Button>
          )}
        </div>
      </div>

      {/* Staged Progress Indicator */}
      {isLoading && (
        <div className="flex flex-col gap-2 rounded-xl border border-primary/20 bg-primary/5 p-3.5">
          <div className="flex items-center justify-between text-xs font-medium">
            <span className="flex items-center gap-2 text-primary">
              <Loader2 className="size-3.5 animate-spin" />
              <span>{currentStage.label}</span>
            </span>
            <span className="font-mono text-muted-foreground tabular-nums">{currentStage.pct}%</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-primary/15">
            <div
              className="h-full rounded-full bg-primary transition-[width] duration-300 ease-out"
              style={{ width: `${currentStage.pct}%` }}
            />
          </div>
        </div>
      )}

      {/* AI Interpretation Summary & Semantic Keywords */}
      {(aiSummary || expandedKeywords.length > 0 || activePills.length > 0) && !isLoading && (
        <div className="flex flex-col gap-3 border-t border-border/60 pt-3.5">
          {aiSummary && (
            <div className="flex items-start justify-between gap-3 rounded-xl border border-primary/20 bg-primary/[0.04] px-3.5 py-2.5">
              <div className="flex items-start gap-2.5">
                <Bot className="size-4 text-primary mt-0.5 shrink-0" aria-hidden="true" />
                <p className="text-sm text-foreground">{aiSummary}</p>
              </div>
              <button
                type="button"
                onClick={onClearSummary}
                className="rounded-lg p-1 text-muted-foreground hover:text-foreground transition-colors"
                aria-label="Dismiss AI summary"
              >
                <X className="size-3.5" />
              </button>
            </div>
          )}

          {(expandedKeywords.length > 0 || activePills.length > 0) && (
            <div className="flex items-center gap-2 flex-wrap">
              {expandedKeywords.map((kw) => (
                <Badge
                  key={kw}
                  variant="secondary"
                  className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium bg-primary/10 text-primary border-transparent"
                >
                  <Sparkles className="size-3" aria-hidden="true" />
                  <span>{kw}</span>
                  {onRemoveKeyword && (
                    <button
                      type="button"
                      onClick={() => onRemoveKeyword(kw)}
                      className="rounded p-0.5 hover:bg-primary/20"
                      aria-label={`Remove keyword ${kw}`}
                    >
                      <X className="size-3" />
                    </button>
                  )}
                </Badge>
              ))}

              {activePills.map((pill) => (
                <Badge
                  key={`${pill.category}-${pill.value}`}
                  variant="outline"
                  className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs font-medium"
                >
                  <span>{pill.label}</span>
                  <button
                    type="button"
                    onClick={() => onRemovePill(pill.category, pill.value)}
                    className="rounded p-0.5 text-muted-foreground hover:text-foreground"
                    aria-label={`Remove filter ${pill.label}`}
                  >
                    <X className="size-3" />
                  </button>
                </Badge>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
