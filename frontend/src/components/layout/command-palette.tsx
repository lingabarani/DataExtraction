"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import {
  LayoutDashboard,
  Building2,
  Users,
  Search,
  MapPin,
  Sparkles,
  Bot,
  Cpu,
  Activity,
  Copy,
  Download,
  Settings,
  KeyRound,
  ArrowRight,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

interface CommandItem {
  id: string;
  label: string;
  group: string;
  href: string;
  icon: React.ElementType;
  hint?: string;
}

const COMMAND_ITEMS: CommandItem[] = [
  { id: "intel", label: "Intelligence Overview", group: "Intelligence", href: "/dashboard", icon: LayoutDashboard, hint: "KPIs & health" },
  { id: "companies", label: "Company Directory", group: "Companies", href: "/companies", icon: Building2, hint: "Master organizations" },
  { id: "vault", label: "US & MX Lead Vault", group: "Companies", href: "/leads", icon: Building2, hint: "Regional registry" },
  { id: "contacts", label: "Executive Contacts", group: "Contacts", href: "/people", icon: Users, hint: "Decision-makers" },
  { id: "discovery", label: "Live Discovery", group: "Discovery", href: "/search", icon: Search, hint: "Multi-source search" },
  { id: "maps", label: "Geo Map Extraction", group: "Discovery", href: "/map-extraction", icon: MapPin, hint: "Spatial scraping" },
  { id: "chatbot", label: "DE AI Chatbot", group: "AI Agent", href: "/chat", icon: Sparkles, hint: "Semantic search" },
  { id: "autonomy", label: "Autonomy Planner", group: "AI Agent", href: "/autonomy", icon: Bot, hint: "Autonomous runs" },
  { id: "orchestration", label: "Temporal Orchestration", group: "Pipeline", href: "/orchestration", icon: Cpu, hint: "Workflows & queues" },
  { id: "pipeline", label: "Data Pipeline & DLQ", group: "Pipeline", href: "/pipeline", icon: Activity, hint: "Stream health" },
  { id: "duplicates", label: "Duplicate Clusters", group: "Pipeline", href: "/duplicates", icon: Copy, hint: "Identity resolution" },
  { id: "export", label: "Export Center", group: "Pipeline", href: "/export", icon: Download, hint: "CSV / Excel exports" },
  { id: "aikeys", label: "AI Keys & Providers", group: "Administration", href: "/settings/ai-keys", icon: KeyRound, hint: "Groq & Ollama" },
  { id: "settings", label: "Workspace Settings", group: "Administration", href: "/settings", icon: Settings, hint: "Preferences" },
];

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const router = useRouter();
  const [query, setQuery] = React.useState("");
  const [activeIndex, setActiveIndex] = React.useState(0);

  const trimmed = query.trim();

  const filtered = React.useMemo(() => {
    if (!trimmed) return COMMAND_ITEMS;
    const lower = trimmed.toLowerCase();
    return COMMAND_ITEMS.filter(
      (item) =>
        item.label.toLowerCase().includes(lower) ||
        item.group.toLowerCase().includes(lower) ||
        (item.hint && item.hint.toLowerCase().includes(lower))
    );
  }, [trimmed]);

  const showAiAskOption = trimmed.length >= 2;
  const totalOptions = filtered.length + (showAiAskOption ? 1 : 0);

  const navigateTo = React.useCallback(
    (href: string) => {
      onOpenChange(false);
      setQuery("");
      setActiveIndex(0);
      router.push(href);
    },
    [onOpenChange, router]
  );

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      setActiveIndex(0);
    }
    onOpenChange(nextOpen);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (totalOptions === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((prev) => (prev + 1) % totalOptions);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((prev) => (prev - 1 + totalOptions) % totalOptions);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (showAiAskOption && activeIndex === 0) {
        navigateTo(`/chat?q=${encodeURIComponent(trimmed)}`);
      } else {
        const itemIdx = showAiAskOption ? activeIndex - 1 : activeIndex;
        const chosen = filtered[itemIdx];
        if (chosen) navigateTo(chosen.href);
      }
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="p-0 overflow-hidden max-w-xl rounded-2xl border-border/80 shadow-card-md duration-0">
        <DialogTitle className="sr-only">Global Command Search</DialogTitle>
        <DialogDescription className="sr-only">
          Jump to any workspace view or run an AI semantic intelligence query.
        </DialogDescription>

        {/* Search Input */}
        <div className="flex items-center gap-3 border-b border-border px-4 py-3.5 bg-card">
          <Search className="size-4 text-muted-foreground shrink-0" aria-hidden="true" />
          <input
            autoFocus
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActiveIndex(0);
            }}
            onKeyDown={handleKeyDown}
            placeholder="Jump to workspace or ask DE AI (e.g. Healthcare in California)..."
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
            aria-label="Command search input"
          />
          <kbd className="hidden sm:inline-flex items-center rounded-md border border-border bg-muted px-1.5 py-0.5 text-[11px] font-mono text-muted-foreground">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div className="max-h-[360px] overflow-y-auto p-2 flex flex-col gap-1 scrollbar-enterprise">
          {showAiAskOption && (
            <button
              type="button"
              onClick={() => navigateTo(`/chat?q=${encodeURIComponent(trimmed)}`)}
              className={cn(
                "w-full flex items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition-colors",
                activeIndex === 0
                  ? "bg-primary/10 text-primary"
                  : "text-foreground hover:bg-muted/70"
              )}
            >
              <span className="flex items-center gap-2.5 min-w-0">
                <span className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground shrink-0">
                  <Sparkles className="size-3.5" />
                </span>
                <span className="truncate font-medium">
                  Ask DE AI: &ldquo;{trimmed}&rdquo;
                </span>
              </span>
              <span className="inline-flex items-center gap-1 text-xs font-medium text-primary shrink-0">
                <span>Search</span>
                <ArrowRight className="size-3.5" />
              </span>
            </button>
          )}

          {filtered.length === 0 && !showAiAskOption ? (
            <div className="py-10 text-center text-sm text-muted-foreground">
              No matching commands found.
            </div>
          ) : (
            filtered.map((item, idx) => {
              const Icon = item.icon;
              const optionIndex = showAiAskOption ? idx + 1 : idx;
              const isSelected = activeIndex === optionIndex;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => navigateTo(item.href)}
                  onMouseEnter={() => setActiveIndex(optionIndex)}
                  className={cn(
                    "w-full flex items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-left transition-colors",
                    isSelected
                      ? "bg-muted text-foreground"
                      : "text-foreground/85 hover:bg-muted/60"
                  )}
                >
                  <span className="flex items-center gap-3 min-w-0">
                    <span className="flex size-8 items-center justify-center rounded-lg border border-border/70 bg-background text-muted-foreground shrink-0">
                      <Icon className="size-4" />
                    </span>
                    <span className="flex flex-col min-w-0">
                      <span className="text-sm font-medium truncate">{item.label}</span>
                      <span className="text-xs text-muted-foreground truncate">{item.group}</span>
                    </span>
                  </span>
                  {item.hint && (
                    <span className="text-xs text-muted-foreground shrink-0 hidden sm:inline">
                      {item.hint}
                    </span>
                  )}
                </button>
              );
            })
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
