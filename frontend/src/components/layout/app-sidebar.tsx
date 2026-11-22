"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, Globe2, BarChart3, Settings,
  Download, Copy, Database, ChevronDown,
  LogOut, Circle, MapPin, Activity, Cpu, Bot, KeyRound, Search,
  Sparkles, ShieldCheck, Building2, Users,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Separator } from "@/components/ui/separator";
import {
  DropdownMenu, DropdownMenuContent,
  DropdownMenuItem, DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/hooks/use-auth";
import { useDbStats } from "@/hooks/use-leads";

// ── Nav structure ─────────────────────────────────────────────────────────────

const PLATFORM_NAV = [
  { label: "Orchestration", href: "/orchestration", icon: Cpu, dot: "green" as const, count: "LIVE" },
];

const PRIMARY_NAV = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "AI Chatbot", href: "/chat", icon: Sparkles, count: "AI" },
  { label: "Company Data", href: "/companies", icon: Building2, count: "213K" },
  { label: "People Data", href: "/people", icon: Users, count: "65K" },
  { label: "Live Discovery", href: "/search", icon: Search, count: "LIVE" },
  { label: "AI Chatbot", href: "/chat", icon: Bot, count: "COPILOT" },
];

const TOOLS_NAV = [
  { label: "Pipeline & DLQ", href: "/pipeline", icon: Activity },
  { label: "Map Extraction", href: "/map-extraction", icon: MapPin },
  { label: "Autonomy", href: "/autonomy", icon: Bot },
  { label: "Duplicates", href: "/duplicates", icon: Copy },
  { label: "Export", href: "/export", icon: Download },
];

const BOTTOM_NAV = [
  { label: "AI Keys", href: "/settings/ai-keys", icon: KeyRound },
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
      prefetch={true}
      className={cn(
        "group flex items-center gap-2.5 px-2.5 py-[7px] rounded text-[13px] transition-all duration-100 active:scale-[0.98]",
        depth === 1 && "pl-8",
        isActive
          ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium shadow-xs border-l-2 border-sidebar-primary rounded-l-none pl-2"
          : "text-sidebar-foreground/75 hover:text-sidebar-foreground hover:bg-sidebar-accent/70"
      )}
    >
      <Icon className={cn(
        "w-[15px] h-[15px] flex-shrink-0 transition-colors",
        isActive ? "text-sidebar-primary" : "text-sidebar-foreground/45 group-hover:text-sidebar-foreground/80"
      )} />
      <span className="flex-1 truncate">{label}</span>
      {dot && <StatusDot color={dot} />}
      {count && (
        <span className={cn(
          "text-[10px] tabnum font-mono px-1.5 py-0.5 rounded transition-colors",
          isActive
            ? "bg-sidebar-primary/20 text-sidebar-primary font-semibold"
            : "bg-sidebar-accent/80 text-sidebar-foreground/50 border border-sidebar-border/50"
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
    <p className="px-2.5 pt-4 pb-1 text-[10px] font-semibold uppercase tracking-wider text-sidebar-foreground/45 select-none">
      {children}
    </p>
  );
}

// ── Sidebar content ───────────────────────────────────────────────────────────

export function SidebarContent() {
  const { user, workspace, logout } = useAuth();
  const { stats } = useDbStats();

  const orgCount = stats?.org_total ? `${Math.round(stats.org_total / 1000)}K` : "213K";
  const peopleCount = (stats?.us_total && stats.us_total < 100000)
    ? `${Math.round(stats.us_total / 1000)}K`
    : (stats?.persons_total ? `${Math.round(stats.persons_total / 1000)}K` : "65K");

  const primaryNavItems = [
    { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
    { label: "Company Data", href: "/companies", icon: Building2, count: orgCount },
    { label: "People Data", href: "/people", icon: Users, count: peopleCount },
    { label: "Live Discovery", href: "/search", icon: Search, count: "LIVE" },
    { label: "AI Chatbot", href: "/chat", icon: Sparkles, count: "AI" },
  ];

  return (
    <div className="flex h-full flex-col bg-sidebar select-none">

      {/* ── Wordmark ──────────────────────────────────────────────── */}
      <div className="flex items-center gap-2.5 px-3.5 h-[52px] border-b border-sidebar-border flex-shrink-0">
        <div className="w-[28px] h-[28px] rounded-md bg-gradient-to-br from-teal-500 to-emerald-600 flex items-center justify-center flex-shrink-0 shadow-sm">
          <Database className="w-[14px] h-[14px] text-white" />
        </div>
        <div className="flex flex-col leading-none">
          <span className="text-[13px] font-bold text-white tracking-tight">
            DataExtraction
          </span>
          <span className="text-[10px] text-sidebar-foreground/50 font-mono mt-0.5">v3.0 • Enterprise</span>
        </div>      
      </div>

      {/* ── Workspace switcher ────────────────────────────────────── */}
      <div className="px-2.5 py-2 border-b border-sidebar-border flex-shrink-0">
        <button className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-sidebar-accent/80 transition-colors border border-sidebar-border/40 bg-sidebar-accent/30">
          <div className="w-[20px] h-[20px] rounded bg-sidebar-primary/20 flex items-center justify-center flex-shrink-0 border border-sidebar-primary/30">
            <span className="text-[9px] font-bold text-sidebar-primary uppercase">
              {(workspace?.name ?? "US").slice(0, 2)}
            </span>
          </div>
          <span className="flex-1 text-left text-[12px] text-sidebar-foreground/80 truncate font-medium">
            {workspace?.name ?? "US & Mexico DB"}
          </span>
          <ChevronDown className="w-3 h-3 text-sidebar-foreground/40 flex-shrink-0" />
        </button>
      </div>

      {/* ── Main nav ──────────────────────────────────────────────── */}
      <nav className="flex-1 overflow-y-auto px-2.5 py-2 space-y-0.5 scrollbar-enterprise">

        <SectionLabel>Platform</SectionLabel>
        {PLATFORM_NAV.map(item => (
          <NavItem key={item.href} {...item} />
        ))}

        <SectionLabel>Data</SectionLabel>
        {primaryNavItems.map(item => (
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
                  {user?.email ?? "admin@dataextraction.com"}
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
              onClick={() => logout()}
              className="text-destructive focus:text-destructive"
            >
              <LogOut className="w-3.5 h-3.5 mr-2" /> Reset session
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}

export function AppSidebar() {
  return (
    <aside className="hidden md:flex w-[240px] flex-shrink-0 border-r border-sidebar-border bg-sidebar z-20 flex-col">
      <SidebarContent />
    </aside>
  );
}
