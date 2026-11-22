"use client";

import React, { useState } from "react";
import {
  Building2,
  Users,
  Search,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ProspectingMode } from "@/lib/prospecting-api";
import { cn } from "@/lib/utils";

interface SearchEngineHubProps {
  mode: ProspectingMode;
  onModeChange?: (mode: ProspectingMode) => void;
  onSelectPrompt: (promptText: string) => void;
  onApplyPreset?: (filterCategory: string, value: string) => void;
  onDirectSearch?: (query: string) => void;
}

export function SearchEngineHub({
  mode,
  onModeChange,
  onSelectPrompt,
  onDirectSearch,
}: SearchEngineHubProps) {
  const [hubQuery, setHubQuery] = useState("");

  const handleSearchSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const q = hubQuery.trim();
    if (!q) return;
    if (onDirectSearch) {
      onDirectSearch(q);
    } else {
      onSelectPrompt(q);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      handleSearchSubmit();
    }
  };

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-6 sm:p-10 text-center min-h-[360px] rounded-xl border border-dashed border-border/80 bg-card/40 backdrop-blur-xs w-full">
      {/* Target Mode Segmented Switcher */}
      {onModeChange && (
        <div className="inline-flex items-center p-0.5 rounded-lg bg-muted/80 border border-border/80 text-xs shadow-2xs mb-4">
          <button
            type="button"
            onClick={() => onModeChange("company")}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1 rounded-md font-medium transition-all text-xs",
              mode === "company"
                ? "bg-background text-foreground shadow-2xs font-semibold"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Building2 className="size-3.5 text-blue-500" />
            <span>Company Search</span>
          </button>
          <button
            type="button"
            onClick={() => onModeChange("people")}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1 rounded-md font-medium transition-all text-xs",
              mode === "people"
                ? "bg-background text-foreground shadow-2xs font-semibold"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Users className="size-3.5 text-purple-500" />
            <span>People Search</span>
          </button>
        </div>
      )}

      {/* Central Query Box */}
      <div className="w-full max-w-xl">
        <form
          onSubmit={handleSearchSubmit}
          className="relative flex items-center gap-2 bg-background/95 rounded-xl border-2 border-border hover:border-primary/50 focus-within:border-primary focus-within:ring-3 focus-within:ring-primary/15 p-1.5 shadow-sm transition-all text-left"
        >
          <div className="flex items-center pl-2.5 text-muted-foreground shrink-0">
            <Search className="size-4 text-primary" />
          </div>

          <Input
            value={hubQuery}
            onChange={(e) => setHubQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              mode === "company"
                ? "Search companies by name, domain, industry, tech stack, or query..."
                : "Search people by job title, name, company domain, or query..."
            }
            className="border-0 shadow-none focus-visible:ring-0 focus-visible:ring-offset-0 px-1 text-xs sm:text-sm bg-transparent placeholder:text-muted-foreground/70"
          />

          {hubQuery && (
            <button
              type="button"
              onClick={() => setHubQuery("")}
              className="p-1 rounded-full text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            >
              <X className="size-3.5" />
            </button>
          )}

          <Button
            type="submit"
            size="sm"
            className="h-8 sm:h-9 px-3 sm:px-4 text-xs font-semibold shrink-0 gap-1.5 shadow-2xs"
          >
            <span>Search</span>
            <kbd className="hidden sm:inline-block text-[10px] font-mono bg-primary-foreground/20 px-1 py-0.2 rounded">
              ↵
            </kbd>
          </Button>
        </form>
      </div>
    </div>
  );
}
