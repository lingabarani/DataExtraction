"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
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
  Database,
  ChevronDown,
  PanelLeftClose,
  PanelLeftOpen,
  LogOut,
  Globe2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Separator } from "@/components/ui/separator";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useAuth } from "@/hooks/use-auth";

const SIDEBAR_STORAGE_KEY = "de_sidebar_collapsed_v1";

interface NavItemConfig {
  label: string;
  href: string;
  icon: React.ElementType;
  badge?: string;
  live?: boolean;
}

interface NavGroupConfig {
  title: string;
  items: NavItemConfig[];
}

const NAV_GROUPS: NavGroupConfig[] = [
  {
    title: "Intelligence",
    items: [
      { label: "Overview", href: "/dashboard", icon: LayoutDashboard },
    ],
  },
  {
    title: "Companies",
    items: [
      { label: "Company Directory", href: "/companies", icon: Building2 },
      { label: "US & MX Vault", href: "/leads", icon: Globe2 },
    ],
  },
  {
    title: "Contacts",
    items: [
      { label: "Decision-Makers", href: "/people", icon: Users },
    ],
  },
  {
    title: "Discovery",
    items: [
      { label: "Live Discovery", href: "/search", icon: Search, badge: "LIVE", live: true },
      { label: "Map Extraction", href: "/map-extraction", icon: MapPin },
    ],
  },
  {
    title: "AI Agent",
    items: [
      { label: "DE Chatbot", href: "/chat", icon: Sparkles, badge: "AI" },
      { label: "Autonomy", href: "/autonomy", icon: Bot },
    ],
  },
  {
    title: "Pipeline",
    items: [
      { label: "Orchestration", href: "/orchestration", icon: Cpu, live: true },
      { label: "Pipeline & DLQ", href: "/pipeline", icon: Activity },
      { label: "Duplicates", href: "/duplicates", icon: Copy },
      { label: "Exports", href: "/export", icon: Download },
    ],
  },
  {
    title: "Administration",
    items: [
      { label: "AI Keys", href: "/settings/ai-keys", icon: KeyRound },
      { label: "Settings", href: "/settings", icon: Settings },
    ],
  },
];

function NavLink({
  item,
  collapsed,
  onNavigate,
}: {
  item: NavItemConfig;
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const isActive =
    pathname === item.href ||
    (item.href !== "/dashboard" && item.href !== "/settings" && pathname.startsWith(item.href));

  const Icon = item.icon;

  const linkNode = (
    <Link
      href={item.href}
      prefetch={false}
      onClick={onNavigate}
      aria-current={isActive ? "page" : undefined}
      className={cn(
        "group relative flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors duration-200 active:scale-[0.98]",
        collapsed && "justify-center px-0 py-2.5",
        isActive
          ? "bg-sidebar-accent text-sidebar-accent-foreground font-semibold"
          : "text-sidebar-foreground hover:bg-muted/70 hover:text-foreground"
      )}
    >
      <Icon
        className={cn(
          "size-[18px] shrink-0 transition-colors",
          isActive
            ? "text-primary"
            : "text-muted-foreground group-hover:text-foreground"
        )}
        aria-hidden="true"
      />
      {!collapsed && <span className="flex-1 truncate">{item.label}</span>}

      {!collapsed && item.live && !item.badge && (
        <span className="size-2 rounded-full bg-success shrink-0" aria-label="Live service" />
      )}

      {!collapsed && item.badge && (
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-mono font-semibold",
            isActive
              ? "bg-primary/15 text-primary"
              : "bg-muted text-muted-foreground"
          )}
        >
          {item.live && <span className="size-1.5 rounded-full bg-success" aria-hidden="true" />}
          {item.badge}
        </span>
      )}
    </Link>
  );

  if (collapsed) {
    return (
      <Tooltip delayDuration={150}>
        <TooltipTrigger asChild>{linkNode}</TooltipTrigger>
        <TooltipContent side="right">{item.label}</TooltipContent>
      </Tooltip>
    );
  }

  return linkNode;
}

export function SidebarContent({
  collapsed = false,
  onToggleCollapse,
  onNavigate,
}: {
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  onNavigate?: () => void;
}) {
  const { user, workspace, logout } = useAuth();

  return (
    <TooltipProvider>
      <div className="flex h-full flex-col bg-sidebar select-none">
        {/* Brand Header */}
        <div
          className={cn(
            "flex h-14 shrink-0 items-center border-b border-sidebar-border px-3.5",
            collapsed ? "justify-center" : "justify-between"
          )}
        >
          <Link
            href="/dashboard"
            className="flex items-center gap-2.5 min-w-0"
            onClick={onNavigate}
          >
            <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
              <Database className="size-4" aria-hidden="true" />
            </div>
            {!collapsed && (
              <div className="flex flex-col leading-none min-w-0">
                <span className="text-sm font-semibold tracking-tight text-foreground truncate">
                  DataExtraction
                </span>
                <span className="mt-0.5 text-[11px] font-mono text-muted-foreground">
                  AI Intelligence
                </span>
              </div>
            )}
          </Link>

          {!collapsed && onToggleCollapse && (
            <button
              type="button"
              onClick={onToggleCollapse}
              className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              aria-label="Collapse sidebar"
              title="Collapse sidebar (Ctrl+B)"
            >
              <PanelLeftClose className="size-4" />
            </button>
          )}
        </div>

        {/* Workspace Pill */}
        {!collapsed && (
          <div className="px-3 py-3 border-b border-sidebar-border shrink-0">
            <div className="flex items-center gap-2.5 rounded-xl border border-border/80 bg-muted/40 px-3 py-2">
              <div className="flex size-6 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-[11px] font-bold text-primary uppercase">
                {(workspace?.name ?? "US").slice(0, 2)}
              </div>
              <span className="flex-1 truncate text-xs font-medium text-foreground">
                {workspace?.name ?? "US & Mexico Vault"}
              </span>
              <ChevronDown className="size-3.5 text-muted-foreground shrink-0" aria-hidden="true" />
            </div>
          </div>
        )}

        {/* Navigation Groups */}
        <nav
          aria-label="Primary Workspace Navigation"
          className="flex-1 overflow-y-auto px-3 py-3 flex flex-col gap-5 scrollbar-enterprise"
        >
          {NAV_GROUPS.map((group) => (
            <div key={group.title} className="flex flex-col gap-1">
              {!collapsed ? (
                <p className="px-3 pb-1 text-xs font-semibold tracking-tight text-muted-foreground/80">
                  {group.title}
                </p>
              ) : (
                <Separator className="my-1 bg-sidebar-border" />
              )}
              <div className="flex flex-col gap-0.5">
                {group.items.map((item) => (
                  <NavLink
                    key={item.href}
                    item={item}
                    collapsed={collapsed}
                    onNavigate={onNavigate}
                  />
                ))}
              </div>
            </div>
          ))}
        </nav>

        {/* Expand Button when Collapsed */}
        {collapsed && onToggleCollapse && (
          <div className="px-3 py-2 border-t border-sidebar-border flex justify-center">
            <Tooltip delayDuration={150}>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  onClick={onToggleCollapse}
                  className="rounded-xl p-2 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                  aria-label="Expand sidebar"
                >
                  <PanelLeftOpen className="size-4" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="right">Expand sidebar (Ctrl+B)</TooltipContent>
            </Tooltip>
          </div>
        )}

        {/* User Footer */}
        <div className="p-3 border-t border-sidebar-border shrink-0">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className={cn(
                  "w-full flex items-center gap-2.5 rounded-xl p-2 hover:bg-muted/70 transition-colors",
                  collapsed && "justify-center px-0"
                )}
                aria-label="Account menu"
              >
                <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary uppercase">
                  {(user?.name ?? "A").charAt(0)}
                </div>
                {!collapsed && (
                  <div className="flex-1 min-w-0 text-left">
                    <p className="truncate text-sm font-medium text-foreground">
                      {user?.name ?? "Admin"}
                    </p>
                    <p className="truncate text-xs text-muted-foreground">
                      {user?.email ?? "admin@dataextraction.com"}
                    </p>
                  </div>
                )}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" side="top" className="w-56 rounded-xl">
              <DropdownMenuItem asChild>
                <Link href="/settings">Workspace settings</Link>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => logout()}
                className="text-destructive focus:text-destructive"
              >
                <LogOut className="size-4 mr-2" /> Reset session
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </TooltipProvider>
  );
}

export function AppSidebar() {
  const [collapsed, setCollapsed] = React.useState(false);

  React.useEffect(() => {
    void Promise.resolve().then(() => {
      try {
        const saved = window.localStorage.getItem(SIDEBAR_STORAGE_KEY);
        if (saved === "true") setCollapsed(true);
      } catch {
        // Ignore storage access restrictions
      }
    });
  }, []);

  const toggleCollapse = React.useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(next));
      } catch {
        // Ignore storage access restrictions
      }
      return next;
    });
  }, []);

  React.useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        toggleCollapse();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [toggleCollapse]);

  return (
    <aside
      className={cn(
        "hidden md:flex shrink-0 flex-col border-r border-sidebar-border bg-sidebar z-20 transition-[width] duration-200 ease-enterprise",
        collapsed ? "w-[72px]" : "w-[248px]"
      )}
    >
      <SidebarContent collapsed={collapsed} onToggleCollapse={toggleCollapse} />
    </aside>
  );
}
