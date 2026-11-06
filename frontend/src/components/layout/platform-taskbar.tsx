"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Cpu,
  Layers,
  Activity,
  Send,
  Clock,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface PlatformNavTab {
  label: string;
  href: string;
  icon: React.ElementType;
  badge?: string;
  badgeColor?: string;
}

const PLATFORM_TABS: PlatformNavTab[] = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Orchestration", href: "/orchestration", icon: Cpu, badge: "LIVE", badgeColor: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border-emerald-500/30" },
  { label: "Data Pipeline", href: "/pipeline", icon: Layers },
  { label: "Observability", href: "/orchestration#observability", icon: Activity },
  { label: "OneReach", href: "/orchestration#onereach", icon: Send },
  { label: "Freshness", href: "/orchestration#freshness", icon: Clock },
  { label: "Administration", href: "/settings", icon: Settings },
];

export function PlatformTaskbar() {
  const pathname = usePathname();
  const [currentHash, setCurrentHash] = useState<string>("");

  useEffect(() => {
    setCurrentHash(typeof window !== "undefined" ? window.location.hash : "");
    const onHashChange = () => {
      setCurrentHash(window.location.hash);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return (
    <div className="border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80 flex-shrink-0 z-20">
      <div className="flex items-center gap-1 overflow-x-auto scrollbar-none px-4 sm:px-6 h-[44px]">
        {PLATFORM_TABS.map((tab) => {
          let isActive = false;
          if (tab.href.includes("#")) {
            const targetHash = tab.href.split("#")[1];
            isActive = pathname.startsWith("/orchestration") && currentHash === `#${targetHash}`;
          } else if (tab.href === "/orchestration") {
            isActive = pathname === "/orchestration" && (!currentHash || currentHash === "#topology");
          } else {
            isActive = pathname === tab.href || (tab.href !== "/dashboard" && pathname.startsWith(tab.href));
          }

          const Icon = tab.icon;

          return (
            <Link
              key={tab.label}
              href={tab.href}
              prefetch={true}
              onClick={(e) => {
                if (tab.href.includes("#")) {
                  const targetHash = tab.href.split("#")[1];
                  if (pathname.startsWith("/orchestration")) {
                    e.preventDefault();
                    window.location.hash = targetHash;
                  }
                  setCurrentHash("#" + targetHash);
                } else {
                  setCurrentHash("");
                }
              }}
              className={cn(
                "group relative flex items-center gap-2 px-3 py-2 text-[12.5px] font-medium transition-all duration-150 whitespace-nowrap rounded-md active:scale-[0.98]",
                isActive
                  ? "text-foreground font-semibold bg-accent/20"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent/10"
              )}
            >
              <Icon
                className={cn(
                  "w-3.5 h-3.5 transition-colors flex-shrink-0",
                  isActive
                    ? "text-primary"
                    : "text-muted-foreground/60 group-hover:text-foreground/80"
                )}
              />
              <span>{tab.label}</span>

              {tab.badge && (
                <span className={cn(
                  "text-[9px] font-mono px-1.5 py-0.2 rounded border font-semibold tracking-wider flex items-center gap-1",
                  tab.badgeColor || "bg-muted text-muted-foreground"
                )}>
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  {tab.badge}
                </span>
              )}

              {isActive && (
                <span className="absolute inset-x-2 bottom-0 h-[2px] bg-primary rounded-t-full shadow-[0_0_8px_rgba(20,184,166,0.5)]" />
              )}
            </Link>
          );
        })}
      </div>
    </div>
  );
}
