"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRouter } from "next/navigation";
import {
  LayoutDashboard, Globe2, BarChart3, Settings,
  Download, Copy, Radio, Database, ChevronDown,
  LogOut, Circle, MapPin, Activity,
  Workflow, Bot, CalendarClock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Separator } from "@/components/ui/separator";
import {
  DropdownMenu, DropdownMenuContent,
  DropdownMenuItem, DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/hooks/use-auth";

// ── Nav structure ─────────────────────────────────────────────────────────────

const PRIMARY_NAV = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "US Leads", href: "/leads", icon: Globe2, count: "906K" },
  { label: "MX Leads", href: "/leads/mexico", icon: Globe2, count: "50K" },
  { label: "AI Query", href: "/analytics", icon: BarChart3 },
];

const ORCHESTRATION_NAV = [
  { label: "Pipelines", href: "/pipelines", icon: Workflow },
  { label: "Agents", href: "/agents", icon: Bot, count: "4" },
  { label: "Schedules", href: "/schedules", icon: CalendarClock },
];

const TOOLS_NAV = [
  { label: "Scraper", href: "/scraper", icon: Radio, dot: "green" as const },
  { label: "Pipeline & DLQ", href: "/pipeline", icon: Activity },
  { label: "Map Extraction", href: "/map-extraction", icon: MapPin },
  { label: "Duplicates", href: "/duplicates", icon: Copy },
  { label: "Export", href: "/export", icon: Download },
];

const BOTTOM_NAV = [
  { label: "Settings", href: "/settings", icon: Settings },
];

// ── Dot types ─────────────────────────────────────────────────────────────────

type DotColor = "green" | "amber" | "red";

function StatusDot({ color }: { color: DotColor }) {
  const map: Record<DotColor, string> = {
    green: "bg-emerald-400",
    amber: "bg-amber-400",
    red: "bg-red-400",
  };
  return <span className={`inline-block w-1.5 h-1.5 rounded-full ${map[color]} flex-shrink-0`} />;
}

// ── Nav item ──────────────────────────────────────────────────────────────────

function NavItem({
  href, label, icon: Icon, count, dot, depth = 0,
}: {
  href: string;
  label: string;
  icon: React.ElementType;
  count?: string;
  dot?: DotColor;
  depth?: number;
}) {
  const pathname = usePathname();
  const isActive = pathname === href || (href !== "/dashboard" && pathname.startsWith(href));

  return (
    <Link
      href={href}
      className={cn(
        "group flex items-center gap-2.5 px-2.5 py-[7px] rounded text-[13px] transition-colors duration-100",
        depth === 1 && "pl-8",
        isActive
          ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
          : "text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent/60"
      )}
    >
      <Icon className={cn(
        "w-[15px] h-[15px] flex-shrink-0",
        isActive ? "text-sidebar-primary" : "text-sidebar-foreground/40 group-hover:text-sidebar-foreground/70"
      )} />
      <span className="flex-1 truncate">{label}</span>
      {dot && <StatusDot color={dot} />}
      {count && (
        <span className={cn(
          "text-[10px] tabnum font-mono px-1.5 py-0.5 rounded",
          isActive
            ? "bg-sidebar-primary/20 text-sidebar-primary"
            : "bg-sidebar-accent text-sidebar-foreground/40"
        )}>
          {count}
        </span>
      )}
    </Link>
  );
}

// ── Section label ─────────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-2.5 pt-4 pb-1 text-[10px] font-semibold uppercase tracking-widest text-sidebar-foreground/30 select-none">
      {children}
    </p>
  );
}

// ── Sidebar content ───────────────────────────────────────────────────────────

export function SidebarContent() {
  const router = useRouter();
  const { user, workspace, logout } = useAuth();

  return (
    <div className="flex h-full flex-col bg-sidebar select-none">

      {/* ── Wordmark ──────────────────────────────────────────────── */}
      <div className="flex items-center gap-2.5 px-3.5 h-[52px] border-b border-sidebar-border flex-shrink-0">
        <div className="w-[26px] h-[26px] rounded-[5px] bg-sidebar-primary flex items-center justify-center flex-shrink-0">
          <Database className="w-[13px] h-[13px] text-white" />
        </div>
        <div className="flex flex-col leading-none">
          <span className="text-[13px] font-semibold text-sidebar-foreground tracking-tight">
            OneExtraction
          </span>
          <span className="text-[10px] text-sidebar-foreground/30 font-mono">v2.1</span>
        </div>      
      </div>

      {/* ── Workspace switcher ────────────────────────────────────── */}
      <div className="px-2.5 py-2 border-b border-sidebar-border flex-shrink-0">
        <button className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded hover:bg-sidebar-accent transition-colors">
          <div className="w-[18px] h-[18px] rounded-sm bg-sidebar-accent flex items-center justify-center flex-shrink-0">
            <span className="text-[9px] font-bold text-sidebar-foreground/60 uppercase">
              {(workspace?.name ?? "US").slice(0, 2)}
            </span>
          </div>
          <span className="flex-1 text-left text-[12px] text-sidebar-foreground/70 truncate">
            {workspace?.name ?? "US & Mexico DB"}
          </span>
          <ChevronDown className="w-3 h-3 text-sidebar-foreground/30 flex-shrink-0" />
        </button>
      </div>

      {/* ── Main nav ──────────────────────────────────────────────── */}
      <nav className="flex-1 overflow-y-auto px-2.5 py-2 space-y-0.5 scrollbar-enterprise">

        <SectionLabel>Data</SectionLabel>
        {PRIMARY_NAV.map(item => (
          <NavItem key={item.href} {...item} />
        ))}

        <SectionLabel>Orchestration</SectionLabel>
        {ORCHESTRATION_NAV.map(item => (
          <NavItem key={item.href} {...item} />
        ))}

        <SectionLabel>Tools</SectionLabel>
        {TOOLS_NAV.map(item => (
          <NavItem key={item.href} {...item} />
        ))}
      </nav>

      <Separator className="bg-sidebar-border" />

      {/* ── Bottom nav ────────────────────────────────────────────── */}
      <div className="px-2.5 py-2 space-y-0.5">
        {BOTTOM_NAV.map(item => (
          <NavItem key={item.href} {...item} />
        ))}
      </div>

      {/* ── User row ──────────────────────────────────────────────── */}
      <div className="px-2.5 pb-3">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded hover:bg-sidebar-accent transition-colors">
              <div className="w-6 h-6 rounded-full bg-sidebar-primary/20 border border-sidebar-primary/30 flex items-center justify-center flex-shrink-0">
                <span className="text-[10px] font-semibold text-sidebar-primary uppercase">
                  {(user?.name ?? "A").charAt(0)}
                </span>
              </div>
              <div className="flex-1 text-left min-w-0">
                <p className="text-[12px] text-sidebar-foreground truncate font-medium">
                  {user?.name ?? "Admin"}
                </p>
                <p className="text-[10px] text-sidebar-foreground/35 truncate font-mono">
                  {user?.email ?? "admin@oneextraction.com"}
                </p>
              </div>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" side="top" className="w-52">
            <DropdownMenuItem asChild>
              <Link href="/settings">Account settings</Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => { logout(); router.push("/login"); }}
              className="text-destructive focus:text-destructive"
            >
              <LogOut className="w-3.5 h-3.5 mr-2" /> Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}

export function AppSidebar() {
  return (
    <aside className="hidden md:flex w-[220px] flex-shrink-0 border-r border-sidebar-border">
      <SidebarContent />
    </aside>
  );
}
