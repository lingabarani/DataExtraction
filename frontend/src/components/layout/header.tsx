"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { Bell, Menu, Search, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SidebarContent } from "@/components/layout/app-sidebar";
import { CommandPalette } from "@/components/layout/command-palette";
import { ThemeToggle } from "@/components/theme-toggle";
import { useTelemetryCache } from "@/hooks/use-telemetry-cache";
import { cn } from "@/lib/utils";

const ROUTE_LABELS: Record<string, string> = {
  dashboard: "Intelligence",
  companies: "Companies",
  company: "Company Profile",
  people: "Contacts",
  orchestration: "Orchestration",
  pipeline: "Pipeline",
  search: "Live Discovery",
  leads: "Vault",
  mexico: "Mexico",
  autonomy: "Autonomy",
  "map-extraction": "Map Extraction",
  duplicates: "Duplicates",
  export: "Exports",
  places: "Place Intelligence",
  org: "Organization Profile",
  "ai-keys": "AI Keys",
  settings: "Settings",
  chat: "DE AI Chatbot",
};

function Breadcrumb() {
  const pathname = usePathname();
  const parts = pathname.split("/").filter(Boolean);

  if (!parts.length) return null;

  return (
    <nav aria-label="Breadcrumb" className="flex items-center gap-2 text-sm min-w-0">
      {parts.map((part, i) => {
        const isLast = i === parts.length - 1;
        const label = ROUTE_LABELS[part] ?? part.charAt(0).toUpperCase() + part.slice(1);
        return (
          <span key={i} className="flex items-center gap-2 min-w-0">
            {i > 0 && (
              <ChevronRight
                className="size-3.5 text-muted-foreground/50 shrink-0"
                aria-hidden="true"
              />
            )}
            <span
              className={cn(
                "truncate tracking-tight",
                isLast ? "font-semibold text-foreground" : "text-muted-foreground"
              )}
            >
              {label}
            </span>
          </span>
        );
      })}
    </nav>
  );
}

export function Header() {
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [commandOpen, setCommandOpen] = React.useState(false);
  const { header } = useTelemetryCache(15000);

  React.useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCommandOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const isHealthy =
    header.database_status !== "OFFLINE" && header.platform_status !== "OFFLINE";

  return (
    <>
      <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-4 border-b border-border/80 glass-surface px-4 sm:px-6 lg:px-10">
        {/* Mobile Navigation Drawer */}
        <div className="md:hidden">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" className="size-9 rounded-xl" aria-label="Open navigation">
                <Menu className="size-4" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="p-0 w-[264px]">
              <SheetTitle className="sr-only">Workspace Navigation</SheetTitle>
              <SidebarContent onNavigate={() => setMobileOpen(false)} />
            </SheetContent>
          </Sheet>
        </div>

        <Breadcrumb />

        <div className="flex-1" />

        {/* Command Search Trigger */}
        <button
          type="button"
          onClick={() => setCommandOpen(true)}
          className="hidden sm:flex items-center gap-3 rounded-xl border border-border/80 bg-muted/50 px-3.5 h-9 text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          aria-label="Open global command search"
        >
          <Search className="size-3.5 shrink-0" aria-hidden="true" />
          <span className="text-xs font-medium">Search intelligence...</span>
          <kbd className="hidden lg:inline-flex items-center gap-0.5 rounded-md border border-border bg-card px-1.5 py-0.5 text-[11px] font-mono text-muted-foreground">
            <span>⌘</span>
            <span>K</span>
          </kbd>
        </button>

        {/* Live Telemetry Pill */}
        <div className="hidden lg:flex items-center gap-2 rounded-full border border-border/80 bg-card px-3 py-1 text-xs font-medium text-muted-foreground">
          <span
            className={cn(
              "size-2 rounded-full",
              isHealthy ? "bg-success" : "bg-warning"
            )}
            aria-hidden="true"
          />
          <span>{isHealthy ? "Engine Online" : "Reconnecting"}</span>
        </div>

        <ThemeToggle />

        {/* System Alerts */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="relative size-9 rounded-xl"
              aria-label="Notifications"
            >
              <Bell className="size-4" />
              <span className="sr-only">System notifications</span>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-80 rounded-2xl p-2">
            <DropdownMenuLabel className="text-xs font-semibold text-muted-foreground px-2 py-1.5">
              System Activity
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem className="flex flex-col items-start gap-1 rounded-xl p-2.5 cursor-default">
              <span className="text-sm font-medium text-foreground">
                Temporal Engine: {header.temporal_status || "DURABLE"}
              </span>
              <span className="text-xs text-muted-foreground">
                {header.active_workflows} active workflows · {header.pending_workflows} queued
              </span>
            </DropdownMenuItem>
            <DropdownMenuItem className="flex flex-col items-start gap-1 rounded-xl p-2.5 cursor-default">
              <span className="text-sm font-medium text-foreground">
                Database Pool: {header.database_status || "CONNECTED"}
              </span>
              <span className="text-xs text-muted-foreground">
                PostgreSQL Master Vault synchronized
              </span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </header>

      <CommandPalette open={commandOpen} onOpenChange={setCommandOpen} />
    </>
  );
}
