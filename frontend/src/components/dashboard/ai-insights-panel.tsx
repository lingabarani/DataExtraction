"use client";

import * as React from "react";
import Link from "next/link";
import {
  Sparkles,
  Lightbulb,
  RefreshCw,
  CheckCircle2,
  Clock,
  ShieldCheck,
  ArrowRight,
  Cpu,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { DbStats } from "@/hooks/use-leads";
import type { HeaderTelemetry, QueueTelemetryItem } from "@/hooks/use-telemetry-cache";
import { formatRelativeSync, formatSourceLabel } from "@/lib/formatters";
import { cn } from "@/lib/utils";

interface EnterpriseWidgetsProps {
  stats: DbStats | null;
  loading: boolean;
  header: HeaderTelemetry;
  queues: QueueTelemetryItem[];
}

export function EnterpriseIntelligenceWidgets({
  stats,
  loading,
  header,
  queues,
}: EnterpriseWidgetsProps) {
  const usTotal = stats?.us_total ?? 0;
  const mxTotal = stats?.mx_total ?? 0;
  const totalLeads = usTotal + mxTotal;

  const emailTotal = (stats?.us_verified_email ?? 0) + (stats?.mx_verified_email ?? 0);
  const phoneTotal = (stats?.us_with_phone ?? 0) + (stats?.mx_with_phone ?? 0);

  const emailCoveragePct = totalLeads > 0 ? Math.round((emailTotal / totalLeads) * 100) : 0;
  const phoneCoveragePct = totalLeads > 0 ? Math.round((phoneTotal / totalLeads) * 100) : 0;
  const enrichedSourcesPct = stats?.by_source?.length
    ? Math.min(100, Math.round((stats.by_source.length / 12) * 100))
    : 0;

  const topIndustry = stats?.by_industry?.[0];
  const topState = stats?.by_state?.[0];
  const topSource = stats?.by_source?.[0];

  const recommendations = React.useMemo(() => {
    const items: Array<{ title: string; detail: string; href: string }> = [];
    if (topIndustry?.industry && topState?.state_code) {
      items.push({
        title: `${topIndustry.industry} leaders in ${topState.state_code}`,
        detail: `${topIndustry.count.toLocaleString("en-US")} verified organizations ready for prospecting`,
        href: `/chat?q=${encodeURIComponent(`${topIndustry.industry} in ${topState.state_code}`)}`,
      });
    } else {
      items.push({
        title: "Explore Healthcare leaders in California",
        detail: "Filter verified corporate records with executive emails",
        href: `/chat?q=${encodeURIComponent("Healthcare companies in California")}`,
      });
    }

    items.push({
      title: "Review Executive Decision-Makers",
      detail: `${(stats?.persons_total ?? 0).toLocaleString("en-US")} C-Suite, VP & Founder profiles`,
      href: "/people",
    });

    items.push({
      title: "Audit Identity Resolution Clusters",
      detail: "Inspect multi-source Splink & domain merges across registries",
      href: "/duplicates",
    });
    return items;
  }, [topIndustry, topState, stats?.persons_total]);

  const activeQueueWorkers = queues.reduce((acc, q) => acc + (q.workers || 0), 0);
  const runningTasks = queues.reduce((acc, q) => acc + (q.running || 0), 0);

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
      {/* ── AI Insights & Smart Recommendations (7 cols) ─────────────── */}
      <section className="lg:col-span-7 flex flex-col gap-6 rounded-2xl border border-border/80 bg-card p-6 shadow-card">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Sparkles className="size-5" aria-hidden="true" />
            </div>
            <div>
              <h2 className="text-lg font-semibold tracking-tight text-foreground">
                AI Insights &amp; Smart Recommendations
              </h2>
              <p className="text-meta text-muted-foreground">
                Automated synthesis from live PostgreSQL &amp; OpenSearch telemetry
              </p>
            </div>
          </div>
          <Badge variant="secondary" className="rounded-lg text-xs font-medium">
            Live Intelligence
          </Badge>
        </div>

        {/* High-signal insights */}
        {loading && !stats ? (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-14 w-full rounded-xl" />
            <Skeleton className="h-14 w-full rounded-xl" />
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="rounded-xl border border-border/70 bg-muted/30 p-4">
              <p className="text-meta text-muted-foreground">Dominant Vertical</p>
              <p className="mt-1 text-sm font-semibold text-foreground truncate">
                {topIndustry?.industry || "Healthcare & Life Sciences"}
              </p>
              <p className="mt-1 text-meta text-muted-foreground tabular-nums">
                {(topIndustry?.count ?? 0).toLocaleString("en-US")} verified organizations
              </p>
            </div>

            <div className="rounded-xl border border-border/70 bg-muted/30 p-4">
              <p className="text-meta text-muted-foreground">Primary Ingestion Stream</p>
              <p className="mt-1 text-sm font-semibold text-foreground truncate">
                {topSource ? formatSourceLabel(topSource.source) : "Master Vault"}
              </p>
              <p className="mt-1 text-meta text-muted-foreground tabular-nums">
                {(topSource?.count ?? 0).toLocaleString("en-US")} entities anchored
              </p>
            </div>
          </div>
        )}

        {/* Smart Recommendations List */}
        <div className="flex flex-col gap-2.5">
          <div className="flex items-center gap-2 text-secondary-label text-foreground">
            <Lightbulb className="size-4 text-warning" aria-hidden="true" />
            <span>Recommended Actions</span>
          </div>
          <div className="flex flex-col gap-2">
            {recommendations.map((rec) => (
              <Link
                key={rec.title}
                href={rec.href}
                className="group flex items-center justify-between gap-4 rounded-xl border border-border/70 bg-background/60 px-4 py-3 transition-colors duration-200 hover:border-primary/40 hover:bg-primary/[0.03]"
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground group-hover:text-primary transition-colors truncate">
                    {rec.title}
                  </p>
                  <p className="text-meta text-muted-foreground truncate">{rec.detail}</p>
                </div>
                <ArrowRight
                  className="size-4 shrink-0 text-muted-foreground transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-primary"
                  aria-hidden="true"
                />
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* ── Data Health, Sync Status & Enrichment Activity (5 cols) ───── */}
      <section className="lg:col-span-5 flex flex-col gap-6 rounded-2xl border border-border/80 bg-card p-6 shadow-card">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-success/10 text-success">
              <ShieldCheck className="size-5" aria-hidden="true" />
            </div>
            <div>
              <h2 className="text-lg font-semibold tracking-tight text-foreground">
                Data Health &amp; Sync Pulse
              </h2>
              <p className="text-meta text-muted-foreground">
                Enrichment coverage, freshness &amp; agent workers
              </p>
            </div>
          </div>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-success/10 px-2.5 py-1 text-meta font-semibold text-success">
            <span className="size-1.5 rounded-full bg-success" aria-hidden="true" />
            {header.temporal_status || "ACTIVE"}
          </span>
        </div>

        {/* Data Health Bars */}
        <div className="flex flex-col gap-4">
          {[
            { label: "Verified Email Coverage", pct: emailCoveragePct, bar: "bg-success" },
            { label: "Direct Phone Coverage", pct: phoneCoveragePct, bar: "bg-primary" },
            { label: "Multi-Source Reconciliation", pct: enrichedSourcesPct, bar: "bg-warning" },
          ].map((metric) => (
            <div key={metric.label} className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between text-meta">
                <span className="text-muted-foreground">{metric.label}</span>
                <span className="font-semibold text-foreground tabular-nums">{metric.pct}%</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className={cn("h-full rounded-full transition-[width] duration-300", metric.bar)}
                  style={{ width: `${Math.min(100, Math.max(0, metric.pct))}%` }}
                />
              </div>
            </div>
          ))}
        </div>

        {/* Recent Enrichment & Worker Status */}
        <div className="border-t border-border/60 pt-4 flex flex-col gap-3">
          <div className="flex items-center justify-between text-secondary-label text-foreground">
            <span className="flex items-center gap-2">
              <Cpu className="size-4 text-primary" aria-hidden="true" />
              <span>Recent Enrichment Activity</span>
            </span>
            <span className="text-meta text-muted-foreground tabular-nums">
              {activeQueueWorkers} workers ready
            </span>
          </div>

          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between rounded-xl bg-muted/40 px-3.5 py-2.5 text-meta">
              <span className="flex items-center gap-2 text-foreground">
                <CheckCircle2 className="size-3.5 text-success shrink-0" aria-hidden="true" />
                <span>AI Enrichment Pipeline</span>
              </span>
              <span className="font-mono text-muted-foreground tabular-nums">
                {runningTasks > 0 ? `${runningTasks} running` : "Standby"}
              </span>
            </div>

            <div className="flex items-center justify-between rounded-xl bg-muted/40 px-3.5 py-2.5 text-meta">
              <span className="flex items-center gap-2 text-foreground">
                <Clock className="size-3.5 text-primary shrink-0" aria-hidden="true" />
                <span>Data Freshness</span>
              </span>
              <span className="font-mono text-muted-foreground tabular-nums">
                {formatRelativeSync(header.last_successful_run?.timestamp)}
              </span>
            </div>

            <div className="flex items-center justify-between rounded-xl bg-muted/40 px-3.5 py-2.5 text-meta">
              <span className="flex items-center gap-2 text-foreground">
                <RefreshCw className="size-3.5 text-muted-foreground shrink-0" aria-hidden="true" />
                <span>OpenSearch Sync Index</span>
              </span>
              <span className="font-mono text-foreground font-semibold">
                {header.opensearch_status || "SYNCED"}
              </span>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
