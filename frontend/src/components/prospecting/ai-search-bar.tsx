"use client";

import React, { useState } from "react";
import {
  Building2,
  Users,
  Sparkles,
  Search,
  Loader2,
  X,
  ArrowRight,
  Bot,
  Terminal,
  Database,
  SlidersHorizontal,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ProspectingMode } from "@/lib/prospecting-api";
import { cn } from "@/lib/utils";

export type SearchProgressStage =
  | "idle"
  | "generating_query"
  | "searching_database"
  | "applying_filters"
  | "rendering";

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
}

export function AiSearchBar({
  mode,
  onModeChange,
  onSearchPrompt,
  isLoading,
  searchStage = "idle",
  synthesizedQuery,
  aiSummary,
  onClearSummary,
  expandedKeywords = [],
  onRemoveKeyword,
  activePills,
  onRemovePill,
  onClearAllPills,
}: AiSearchBarProps) {
  const [prompt, setPrompt] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim() || isLoading) return;
    onSearchPrompt(prompt.trim());
  };

  const stageProgressMap: Record<SearchProgressStage, { label: string; pct: number }> = {
    idle: { label: "Ready", pct: 0 },
    generating_query: { label: "Generating query... (15%)", pct: 15 },
    searching_database: { label: "Searching database... (45%)", pct: 45 },
    applying_filters: { label: "Applying filters... (75%)", pct: 75 },
    rendering: { label: "Rendering results... (100%)", pct: 100 },
  };

  const currentStage = stageProgressMap[searchStage] || stageProgressMap.searching_database;

  return (
    <div className="w-full flex flex-col gap-2.5 rounded-xl border border-border/70 bg-card/60 backdrop-blur-md p-3.5 shadow-xs">
      {/* Search Input Bar with Mode Switcher */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2">
        {/* Mode Segmented Toggle */}
        <div
          role="radiogroup"
          aria-label="Target Mode"
          className="inline-flex items-center rounded-lg border border-border/80 bg-background/90 p-1 shadow-2xs shrink-0"
        >
          <button
            type="button"
            role="radio"
            aria-checked={mode === "company"}
            onClick={() => onModeChange("company")}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all duration-150 active:scale-[0.98]",
              mode === "company"
                ? "bg-blue-600 text-white shadow-xs font-semibold"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
            )}
          >
            <Building2 className="size-3.5" />
            <span>Company</span>
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={mode === "people"}
            onClick={() => onModeChange("people")}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all duration-150 active:scale-[0.98]",
              mode === "people"
                ? "bg-purple-600 text-white shadow-xs font-semibold"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
            )}
          >
            <Users className="size-3.5" />
            <span>People</span>
          </button>
        </div>

        {/* Natural Language Search Input */}
        <form onSubmit={handleSubmit} className="relative flex-1 flex items-center">
          <div className="absolute left-3.5 text-muted-foreground pointer-events-none">
            <Search className="size-4" />
          </div>
          <Input
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder={
              mode === "company"
                ? "Search companies by name, domain, industry, tech stack, or natural language query..."
                : "Search people by job title, name, department, company domain, or query..."
            }
            disabled={isLoading}
            className="h-10 pl-10 pr-24 rounded-lg bg-background/90 border-border/80 text-xs sm:text-sm focus-visible:ring-2 focus-visible:ring-primary shadow-inner"
          />
          <div className="absolute right-1.5 flex items-center gap-1">
            {prompt && (
              <button
                type="button"
                onClick={() => setPrompt("")}
                className="p-1 text-muted-foreground hover:text-foreground rounded-md transition-colors"
                title="Clear input"
              >
                <X className="size-3.5" />
              </button>
            )}
            <Button
              type="submit"
              size="sm"
              disabled={isLoading || !prompt.trim()}
              className={cn(
                "h-7 px-3 rounded-md text-xs font-medium gap-1.5 transition-all shadow-xs",
                mode === "company"
                  ? "bg-blue-600 hover:bg-blue-700 text-white"
                  : "bg-purple-600 hover:bg-purple-700 text-white"
              )}
            >
              {isLoading ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <>
                  <span>Search</span>
                  <ArrowRight className="size-3" />
                </>
              )}
            </Button>
          </div>
        </form>
      </div>

      {/* Enterprise-Grade Staged Loading & Progress Indicator */}
      {isLoading && (
        <div className="w-full flex flex-col gap-1.5 p-2.5 rounded-lg bg-primary/5 border border-primary/20">
          <div className="flex items-center justify-between text-xs font-medium text-foreground">
            <span className="flex items-center gap-1.5 text-primary">
              <Loader2 className="size-3.5 animate-spin" />
              <span>{currentStage.label}</span>
            </span>
            <span className="font-mono text-[11px] text-muted-foreground">{currentStage.pct}%</span>
          </div>
          <div className="w-full h-1.5 rounded-full bg-primary/15 overflow-hidden">
            <div
              className="h-full bg-primary transition-all duration-300 ease-out rounded-full"
              style={{ width: `${currentStage.pct}%` }}
            />
          </div>
        </div>
      )}

      {/* Transparent Synthesized Query Display */}
      {synthesizedQuery && !isLoading && (
        <div className="flex items-center gap-2 p-2 rounded-lg bg-muted/40 border border-border/60 text-xs">
          <Terminal className="size-3.5 text-primary shrink-0" />
          <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider shrink-0">
            Synthesized Query:
          </span>
          <span className="font-mono text-[11px] text-foreground/90 truncate flex-1" title={synthesizedQuery}>
            {synthesizedQuery}
          </span>
        </div>
      )}

      {/* Groq Semantic Expanded Keywords Bar */}
      {expandedKeywords && expandedKeywords.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap p-2 rounded-lg bg-blue-500/5 dark:bg-blue-500/10 border border-blue-500/15">
          <span className="text-[11px] font-semibold text-blue-600 dark:text-blue-400 uppercase tracking-wider flex items-center gap-1 shrink-0">
            <Sparkles className="size-3" />
            Expanded Synonyms:
          </span>
          <div className="flex items-center gap-1.5 flex-wrap">
            {expandedKeywords.map((kw) => (
              <Badge
                key={kw}
                variant="outline"
                className="flex items-center gap-1 text-[11px] py-0.5 pl-2 pr-1 rounded-md bg-background/80 text-foreground border-blue-500/25 shadow-2xs"
              >
                <span>{kw}</span>
                {onRemoveKeyword && (
                  <button
                    type="button"
                    onClick={() => onRemoveKeyword(kw)}
                    className="rounded hover:bg-muted p-0.5 text-muted-foreground hover:text-foreground transition-colors"
                    title={`Remove synonym "${kw}"`}
                  >
                    <X className="size-3" />
                  </button>
                )}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* AI Assistant Summary Box (when available) */}
      {aiSummary && (
        <div className="flex items-start justify-between gap-3 p-2.5 rounded-lg bg-primary/5 border border-primary/15 text-xs">
          <div className="flex items-start gap-2">
            <div className="p-1 rounded bg-primary/10 text-primary mt-0.5">
              <Bot className="size-3.5" />
            </div>
            <div>
              <p className="font-medium text-foreground">{aiSummary}</p>
              <p className="text-[11px] text-muted-foreground mt-0.5">
                Applied filters combined with database criteria.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClearSummary}
            className="text-muted-foreground hover:text-foreground p-1 rounded hover:bg-background/80 transition-colors"
            title="Dismiss summary"
          >
            <X className="size-3.5" />
          </button>
        </div>
      )}

      {/* Active Filter Pills Bar */}
      {activePills.length > 0 && (
        <div className="flex items-center justify-between gap-2 pt-2 border-t border-border/40 flex-wrap">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mr-1">
              Active Filters:
            </span>
            {activePills.map((pill) => (
              <Badge
                key={`${pill.category}-${pill.value}`}
                variant="secondary"
                className="flex items-center gap-1 text-[11px] py-0.5 pl-2 pr-1 rounded-md bg-secondary/80 text-secondary-foreground border border-border/60"
              >
                <span>{pill.label}</span>
                <button
                  type="button"
                  onClick={() => onRemovePill(pill.category, pill.value)}
                  className="rounded hover:bg-muted p-0.5 text-muted-foreground hover:text-foreground"
                >
                  <X className="size-3" />
                </button>
              </Badge>
            ))}
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={onClearAllPills}
            className="h-6 text-[11px] text-muted-foreground hover:text-destructive px-2 py-0"
          >
            Clear All
          </Button>
        </div>
      )}
    </div>
  );
}
