"use client";

import * as React from "react";
import Link from "next/link";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { useDbStats } from "@/hooks/use-leads";
import { useTelemetryCache } from "@/hooks/use-telemetry-cache";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { HeroKpiGrid } from "@/components/dashboard/hero-kpi-grid";
import { EnterpriseIntelligenceWidgets } from "@/components/dashboard/ai-insights-panel";
import { formatSourceLabel } from "@/lib/formatters";
import {
  Download,
  RefreshCw,
  Sparkles,
  ArrowRight,
} from "lucide-react";
import { toast } from "sonner";

const SOURCE_BAR_COLORS = [
  "hsl(var(--data-1))",
  "hsl(var(--data-2))",
  "hsl(var(--data-3))",
  "hsl(var(--data-4))",
  "hsl(var(--data-5))",
  "hsl(var(--data-6))",
];

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ value: number }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  const count = payload[0].value;
  return (
    <div className="rounded-xl border border-border bg-popover px-3.5 py-2.5 text-xs shadow-card-md">
      <p className="font-semibold text-foreground">{formatSourceLabel(String(label))}</p>
      <p className="mt-1 font-mono font-semibold text-primary tabular-nums">
        {count.toLocaleString("en-US")} verified entities
      </p>
    </div>
  );
}

export function DashboardOverview() {
  const { stats, loading, refresh } = useDbStats();
  const { header, queues, refresh: refreshTelemetry } = useTelemetryCache(15000);
  const [isRefreshing, setIsRefreshing] = React.useState(false);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await Promise.all([refresh(), refreshTelemetry()]);
    toast.success("Intelligence metrics synchronized", {
      description: "Live counts refreshed from PostgreSQL Master Vault.",
    });
    setIsRefreshing(false);
  };

  return (
    <div className="flex flex-col gap-8">
      {/* ── Page Header (32px Enterprise Scale) ─────────────────────── */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-page-header text-foreground">Data Intelligence</h1>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-success/10 px-3 py-1 text-meta font-semibold text-success">
              <span className="size-1.5 rounded-full bg-success" aria-hidden="true" />
              Master Vault Active
            </span>
          </div>
          <p className="text-body-base text-muted-foreground max-w-[65ch]">
            Unified entity resolution, source provenance, and AI-powered discovery across corporate and executive records.
          </p>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="h-10 rounded-xl px-4 text-sm font-medium gap-2"
          >
            <RefreshCw className={`size-4 ${isRefreshing ? "animate-spin text-primary" : ""}`} />
            <span>Sync Metrics</span>
          </Button>
          <Button asChild variant="outline" size="sm" className="h-10 rounded-xl px-4 text-sm font-medium gap-2">
            <Link href="/export">
              <Download className="size-4" />
              <span>Export</span>
            </Link>
          </Button>
          <Button asChild size="sm" className="h-10 rounded-xl px-4 text-sm font-medium gap-2">
            <Link href="/chat">
              <Sparkles className="size-4" />
              <span>AI Search</span>
            </Link>
          </Button>
        </div>
      </div>

      {/* ── Hero KPI Cards ──────────────────────────────────────────── */}
      <HeroKpiGrid stats={stats} header={header} loading={loading} />

      {/* ── Enterprise AI Insights & Data Health ────────────────────── */}
      <EnterpriseIntelligenceWidgets
        stats={stats}
        loading={loading}
        header={header}
        queues={queues}
      />

      {/* ── Source Volume & Regional Breakdown ──────────────────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        <section className="lg:col-span-7 rounded-2xl border border-border/80 bg-card p-6 shadow-card flex flex-col gap-5">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-section-title text-foreground">Source Distribution</h2>
              <p className="text-meta text-muted-foreground mt-0.5">
                Records ingested and reconciled across authoritative providers
              </p>
            </div>
            <Link
              href="/orchestration"
              className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline shrink-0"
            >
              <span>Inspect Pipelines</span>
              <ArrowRight className="size-3.5" aria-hidden="true" />
            </Link>
          </div>

          {loading && !stats ? (
            <div className="flex flex-col gap-3 py-4">
              {[1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} className="h-6 w-full rounded-lg" />
              ))}
            </div>
          ) : (
            <div className="h-[260px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={(stats?.by_source ?? []).slice(0, 8)}
                  layout="vertical"
                  margin={{ top: 4, right: 16, left: 24, bottom: 4 }}
                  barSize={16}
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="hsl(var(--border))"
                    horizontal={false}
                    opacity={0.7}
                  />
                  <XAxis
                    type="number"
                    tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }}
                    tickFormatter={(v) => (v >= 1000 ? `${Math.round(v / 1000)}K` : String(v))}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="source"
                    width={110}
                    tick={{ fontSize: 12, fill: "hsl(var(--foreground))" }}
                    tickFormatter={formatSourceLabel}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip content={<ChartTooltip />} cursor={{ fill: "hsl(var(--muted) / 0.5)" }} />
                  <Bar dataKey="count" radius={[0, 8, 8, 0]}>
                    {(stats?.by_source ?? []).slice(0, 8).map((_, idx) => (
                      <Cell key={idx} fill={SOURCE_BAR_COLORS[idx % SOURCE_BAR_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>

        {/* Top Industries */}
        <section className="lg:col-span-5 rounded-2xl border border-border/80 bg-card p-6 shadow-card flex flex-col gap-5">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h2 className="text-section-title text-foreground">Top Industries</h2>
              <p className="text-meta text-muted-foreground mt-0.5">
                Leading market segments in the Master Vault
              </p>
            </div>
            <Link
              href="/companies"
              className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline shrink-0"
            >
              <span>View All</span>
              <ArrowRight className="size-3.5" aria-hidden="true" />
            </Link>
          </div>

          {loading && !stats ? (
            <div className="flex flex-col gap-3">
              {[1, 2, 3, 4, 5, 6].map((i) => (
                <Skeleton key={i} className="h-8 w-full rounded-lg" />
              ))}
            </div>
          ) : (
            <div className="flex flex-col divide-y divide-border/60">
              {(stats?.by_industry ?? []).slice(0, 6).map((ind, idx) => {
                const maxVal = stats?.by_industry?.[0]?.count ?? 1;
                const pct = Math.max(4, Math.round((ind.count / maxVal) * 100));
                return (
                  <div
                    key={ind.industry || idx}
                    className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0"
                  >
                    <div className="flex items-center gap-3 min-w-0 flex-1">
                      <span className="w-5 text-meta font-mono text-muted-foreground shrink-0">
                        {idx + 1}
                      </span>
                      <span className="text-sm font-medium text-foreground truncate">
                        {ind.industry || "Commercial Services"}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <div className="hidden sm:block h-1.5 w-20 overflow-hidden rounded-full bg-muted">
                        <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
                      </div>
                      <span className="w-16 text-right text-xs font-mono font-semibold text-foreground tabular-nums">
                        {ind.count.toLocaleString("en-US")}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
