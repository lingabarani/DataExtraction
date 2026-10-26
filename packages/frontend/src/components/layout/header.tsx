"use client";

import { usePathname } from "next/navigation";
import { Bell, Menu, Search, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import {
  DropdownMenu, DropdownMenuContent,
  DropdownMenuItem, DropdownMenuLabel,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SidebarContent } from "@/components/layout/app-sidebar";
import { ThemeToggle } from "@/components/theme-toggle";
import { cn } from "@/lib/utils";

// ── Breadcrumb builder ────────────────────────────────────────────────────────

const LABELS: Record<string, string> = {
  dashboard:  "Dashboard",
  leads:      "US Leads",
  mexico:     "MX Leads",
  analytics:  "AI Query",
  scraper:    "Scraper",
  duplicates: "Duplicates",
  export:     "Export",
  settings:   "Settings",
};

function Breadcrumb() {
  const pathname = usePathname();
  const parts    = pathname.split("/").filter(Boolean);

  if (!parts.length) return null;

  return (
    <nav className="flex items-center gap-1 text-[13px]">
      {parts.map((part, i) => {
        const isLast  = i === parts.length - 1;
        const label   = LABELS[part] ?? part.charAt(0).toUpperCase() + part.slice(1);
        return (
          <span key={i} className="flex items-center gap-1">
            {i > 0 && <ChevronRight className="w-3 h-3 text-muted-foreground/40" />}
            <span className={cn(
              isLast ? "font-medium text-foreground" : "text-muted-foreground"
            )}>
              {label}
            </span>
          </span>
        );
      })}
    </nav>
  );
}

// ── Notification data ─────────────────────────────────────────────────────────

const NOTIFICATIONS = [
  { title: "CMS NPI ingestion complete", detail: "885,500 healthcare records loaded", time: "2h ago" },
  { title: "Duplicate analysis ready",   detail: "1,842 removable records found",     time: "4h ago" },
  { title: "SAM.gov API timeout",        detail: "Server unreachable — retry pending", time: "6h ago" },
];

// ── Header ────────────────────────────────────────────────────────────────────

export function Header() {
  return (
    <header className="h-[52px] border-b border-border flex items-center gap-4 px-4 sm:px-5 bg-background flex-shrink-0 sticky top-0 z-30">

      {/* Mobile hamburger */}
      <Sheet>
        <SheetTrigger asChild>
          <Button variant="ghost" size="icon" className="md:hidden h-8 w-8">
            <Menu className="h-4 w-4" />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="p-0 w-[220px]">
          <SidebarContent />
        </SheetContent>
      </Sheet>

      {/* Breadcrumb */}
      <Breadcrumb />

      {/* Spacer */}
      <div className="flex-1" />

      {/* Right controls */}
      <div className="flex items-center gap-0.5">

        {/* Command search hint */}
        <button className="hidden sm:flex items-center gap-2 px-3 h-8 rounded border border-border bg-muted/50 hover:bg-muted transition-colors text-muted-foreground mr-2">
          <Search className="w-3.5 h-3.5" />
          <span className="text-[12px]">Search...</span>
          <kbd className="hidden lg:inline-flex items-center gap-0.5 text-[10px] font-mono bg-background border border-border rounded px-1 py-0.5">
            <span>⌘</span><span>K</span>
          </kbd>
        </button>

        <ThemeToggle />

        {/* Notifications */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-8 w-8 relative">
              <Bell className="h-4 w-4" />
              <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 bg-amber-500 rounded-full" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-80">
            <DropdownMenuLabel className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Notifications
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            {NOTIFICATIONS.map(n => (
              <DropdownMenuItem key={n.title} className="flex flex-col items-start gap-0.5 py-2.5 cursor-default">
                <span className="text-[13px] font-medium">{n.title}</span>
                <span className="text-xs text-muted-foreground">{n.detail}</span>
                <span className="text-[11px] text-muted-foreground/50 font-mono">{n.time}</span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
