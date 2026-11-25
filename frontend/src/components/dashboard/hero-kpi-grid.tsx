"use client";

import * as React from "react";
import Link from "next/link";
import {
  Building2,
  Database,
  ShieldCheck,
  Activity,
  ArrowUpRight,
} from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { DbStats } from "@/hooks/use-leads";
import type { HeaderTelemetry } from "@/hooks/use-telemetry-cache";
import { formatRelativeSync, normalizePercentScore } from "@/lib/formatters";

interface HeroKpiCardProps {
  title: string;
  value: string | number | undefined;
  meta: string;
  href: string;
  icon: React.ElementType;
  badge?: {
    label: string;
    tone: "primary" | "success" | "warning" | "danger";
  };
  progressPct?: number;
  loading?: boolean;
}

function HeroKpiCard({
  title,
  value,
  meta,
  href,
  icon: Icon,
  badge,
  progressPct,
  loading,
}: HeroKpiCardProps) {
  return (
    <Link
      href={href}
      className="group block rounded-2xl border border-border/80 bg-card p-6 shadow-card transition-[transform,box-shadow,border-color] duration-200 ease-enterprise hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-card-md active:scale-[0.98]"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-secondary-label text-muted-foreground">{title}</span>
        <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <Icon className="size-5" aria-hidden="true" />
        </div>
      </div>

      <div className="mt-4 flex items-baseline justify-between gap-3">
        {loading && value === undefined ? (
          <Skeleton className="h-9 w-28 rounded-lg" />
        ) : (
          <span className="text-[32px] font-semibold leading-[1.15] tracking-[-0.025em] text-foreground tabular-nums">
            {typeof value === "number" ? value.toLocaleString("en-US") : value}
          </span>
        )}

        {badge && (
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-meta font-semibold",
              badge.tone === "primary" && "bg-primary/10 text-primary",
              badge.tone === "success" && "bg-success/15 text-success",
              badge.tone === "warning" && "bg-warning/15 text-warning",
              badge.tone === "danger" && "bg-destructive/15 text-destructive"
            )}
          >
            {badge.label}
          </span>
        )}
      </div>

      {progressPct !== undefined && (
        <div className="mt-4 h-2 w-full overflow-hidden rounded-full bg-muted">
          <div
            className={cn(
              "h-full rounded-full transition-[width] duration-300 ease-out",
              progressPct >= 80
                ? "bg-success"
                : progressPct >= 50
                  ? "bg-warning"
                  : "bg-destructive"
            )}
            style={{ width: `${Math.min(100, Math.max(0, progressPct))}%` }}
          />
        </div>
      )}

      <div className="mt-4 flex items-center justify-between gap-2 pt-3 border-t border-border/50">
        <span className="text-meta text-muted-foreground truncate">{meta}</span>
        <ArrowUpRight
          className="size-4 shrink-0 text-muted-foreground/40 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-primary"
          aria-hidden="true"
        />
      </div>
    </Link>
  );
}

interface HeroKpiGridProps {
  stats: DbStats | null;
  header: HeaderTelemetry;
  loading: boolean;
}

export function HeroKpiGrid({ stats, header, loading }: HeroKpiGridProps) {
  const totalCompanies =
    stats?.organizations_total ??
    stats?.org_total ??
    (stats ? stats.us_total + stats.mx_total : undefined);

  const activeSources = stats?.by_source?.length;

  const qualityScore = React.useMemo(() => {
    if (!stats?.by_source?.length) return undefined;
    const totalWeight = stats.by_source.reduce((sum, s) => sum + (s.count || 0), 0);
    if (!totalWeight) return undefined;
    const weighted = stats.by_source.reduce(
      (sum, s) => sum + normalizePercentScore(s.avg_score, 88) * (s.count || 0),
      0
    );
    return Math.round((weighted / totalWeight) * 10) / 10;
  }, [stats]);

  const lastSyncText = header.last_successful_run?.timestamp
    ? formatRelativeSync(header.last_successful_run.timestamp)
    : "Live";

  const isHealthy =
    header.database_status !== "OFFLINE" && header.temporal_status !== "OFFLINE";

  return (
    <section aria-label="Key Intelligence Metrics" className="grid grid-cols-1 gap-6 sm:grid-cols-2 xl:grid-cols-4">
      <HeroKpiCard
        title="Total Companies"
        value={totalCompanies}
        meta="Verified sovereign entities across US & Mexico"
        href="/companies"
        icon={Building2}
        badge={
          stats?.persons_total
            ? {
                label: `${stats.persons_total.toLocaleString("en-US")} contacts`,
                tone: "primary",
              }
            : undefined
        }
        loading={loading}
      />

      <HeroKpiCard
        title="Active Sources"
        value={activeSources}
        meta="Federal registries, Google Maps & Open Directories"
        href="/orchestration"
        icon={Database}
        badge={{ label: "Multi-source", tone: "success" }}
        loading={loading}
      />

      <HeroKpiCard
        title="Data Quality Score"
        value={qualityScore !== undefined ? `${qualityScore}%` : undefined}
        meta="Weighted trust across entity clustering & validation"
        href="/pipeline"
        icon={ShieldCheck}
        progressPct={qualityScore ?? 0}
        badge={
          qualityScore !== undefined
            ? {
                label: qualityScore >= 85 ? "Optimal" : "Nominal",
                tone: qualityScore >= 85 ? "success" : "warning",
              }
            : undefined
        }
        loading={loading}
      />

      <HeroKpiCard
        title="Recent Sync Status"
        value={lastSyncText}
        meta={`${header.active_workflows} active workflows · ${header.database_status || "CONNECTED"}`}
        href="/orchestration"
        icon={Activity}
        badge={{
          label: isHealthy ? "Operational" : "Degraded",
          tone: isHealthy ? "success" : "warning",
        }}
        loading={false}
      />
    </section>
  );
}
