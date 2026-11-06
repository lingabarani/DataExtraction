"use client";

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

interface NavTab {
  label: string;
  href: string;
  icon: React.ElementType;
  isExternalOrHash?: boolean;
}

const NAV_TABS: NavTab[] = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Orchestration", href: "/orchestration", icon: Cpu },
  { label: "Data Pipeline", href: "/pipeline", icon: Layers },
  { label: "Observability", href: "#observability", icon: Activity, isExternalOrHash: true },
  { label: "OneReach", href: "#onereach", icon: Send, isExternalOrHash: true },
  { label: "Freshness", href: "#freshness", icon: Clock, isExternalOrHash: true },
  { label: "Administration", href: "/settings", icon: Settings },
];

export function OrchestrationTopNav() {
  const pathname = usePathname();

  return (
    <div className="border-b border-border/80 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="flex items-center gap-1 overflow-x-auto scrollbar-none px-4 sm:px-6">
        {NAV_TABS.map((tab) => {
          const isActive = pathname === tab.href || (tab.href !== "/dashboard" && pathname.startsWith(tab.href));
          const Icon = tab.icon;

          return (
            <Link
              key={tab.label}
              href={tab.href}
              className={cn(
                "group relative flex items-center gap-2 px-3.5 py-3 text-[13px] font-medium transition-all duration-150 whitespace-nowrap",
                isActive
                  ? "text-primary"
                  : "text-muted-foreground/70 hover:text-foreground hover:bg-muted/40"
              )}
            >
              <Icon
                className={cn(
                  "w-4 h-4 transition-colors",
                  isActive
                    ? "text-primary"
                    : "text-muted-foreground/50 group-hover:text-foreground/80"
                )}
              />
              <span>{tab.label}</span>

              {isActive && (
                <span className="absolute inset-x-0 bottom-0 h-0.5 bg-primary shadow-[0_0_8px_rgba(59,130,246,0.6)]" />
              )}
            </Link>
          );
        })}
      </div>
    </div>
  );
}

