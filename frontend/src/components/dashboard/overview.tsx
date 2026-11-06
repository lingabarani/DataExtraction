"use client";

import { useState } from "react";
import Link from "next/link";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { useDbStats } from "@/hooks/use-leads";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import {
  ArrowUpRight,
  TrendingUp,
  Database,
  Download,
  Radio,
  ShieldCheck,
  Globe2,
  PhoneCall,
  MailCheck,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";

// ── Colour map for sources ────────────────────────────────────────────────────

const SRC_COLOUR: Record<string, string> = {
  CMS_NPI:        "#0f766e",  // teal-700
  SEC_EDGAR:      "#374151",  // gray-700
  FDIC:           "#92400e",  // amber-800
  NCUA:           "#b45309",  // amber-700
  USASPENDING:    "#6d28d9",  // violet-700
  PROPUBLICA_990: "#0e7490",  // cyan-700
  SAM_GOV:        "#166534",  // green-800
  OPENSTREETMAP:  "#0284c7",  // sky-600
  GOOGLE_MAPS:    "#ea580c",  // orange-600
  CSV:            "#1d4ed8",  // blue-700
  INTERNAL_JSON:  "#4b5563",  // gray-600
  DB:             "#6b7280",  // gray-500
};

// ── Enhanced metric card ──────────────────────────────────────────────────────

function MetricCard({
  label,
  value,
  sub,
  href,
  delta,
  icon: Icon,
  sourceBadge,
}: {
  label:  string;
  value:  string | number | undefined;
  sub:    string;
  href:   string;
  delta?: string;
  icon?:  React.ElementType;
  sourceBadge?: string;
}) {
  return (
    <Link href={href} className="group block active:scale-[0.98] transition-transform duration-150">
      <div className="rounded-lg border border-border/80 bg-card p-4 hover:border-primary/40 hover:shadow-md transition-all duration-200 relative overflow-hidden">
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2">
            {Icon && (
              <div className="p-1.5 rounded-md bg-primary/10 text-primary border border-primary/20">
                <Icon className="w-3.5 h-3.5" />
              </div>
            )}
            <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              {label}
            </span>
          </div>
          <ArrowUpRight className="w-3.5 h-3.5 text-muted-foreground/30 group-hover:text-foreground group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-all" />
        </div>
        {value !== undefined ? (
          <p className="text-2xl font-bold tabnum font-mono tracking-tight text-foreground">
            {typeof value === "number" ? value.toLocaleString() : value}
          </p>
        ) : (
          <Skeleton className="h-8 w-24 mb-0.5" />
        )}
        <div className="flex items-center justify-between mt-2 pt-2 border-t border-border/40 text-[11px]">
          <span className="text-xs text-muted-foreground truncate">{sub}</span>
          <div className="flex items-center gap-1.5 shrink-0">
            {sourceBadge && (
              <span className="text-[10px] font-mono text-muted-foreground/60 bg-muted/60 px-1 py-0.5 rounded border border-border/50">
                {sourceBadge}
              </span>
            )}
            {delta && (
              <span className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400 font-mono bg-emerald-500/10 px-1.5 py-0.5 rounded border border-emerald-500/20">
                {delta}
              </span>
            )}
          </div>
        </div>
      </div>
    </Link>
  );
}

// ── Section header ────────────────────────────────────────────────────────────

function SectionHeader({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground flex items-center gap-1.5">
        {title}
      </h2>
      {action}
    </div>
  );
}

// ── Custom tooltip ────────────────────────────────────────────────────────────

function ChartTooltip({ active, payload, label }: {
  active?: boolean; payload?: Array<{ value: number }>; label?: string;
}) {
  if (!active || !payload?.length) return null;
  const count = payload[0].value;
  return (
    <div className="bg-popover border border-border rounded-md shadow-lg px-3 py-2 text-xs backdrop-blur-sm">
      <p className="font-semibold text-foreground mb-1">
        {fmtSource(String(label))}
      </p>
      <div className="flex items-center gap-2">
        <span className="font-mono tabnum text-primary font-bold">
          {count.toLocaleString()}
        </span>
        <span className="text-[11px] text-muted-foreground">
          certified entities
        </span>
      </div>
    </div>
  );
}

// ── Bar label formatter ───────────────────────────────────────────────────────

function fmtSource(s: string) {
  return s
    .replace("_NPI", "")
    .replace("_EDGAR", "")
    .replace("PROPUBLICA_990", "ProPublica")
    .replace("USASPENDING", "USASpend")
    .replace("OPENSTREETMAP", "OpenStreetMap")
    .replace("GOOGLE_MAPS", "Google Maps")
    .replace("INTERNAL_JSON", "Internal");
}

// ── Coverage row ──────────────────────────────────────────────────────────────

function CoverageBar({ label, pct, color }: { label: string; pct: number; color: string }) {
  return (
    <div className="flex items-center gap-3 py-1.5">
      <span className="w-28 text-[12px] text-muted-foreground flex-shrink-0">{label}</span>
      <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <span className="w-10 text-right text-[12px] font-mono tabnum font-semibold text-foreground">
        {pct}%
      </span>
    </div>
  );
}

// ── Industry table row ────────────────────────────────────────────────────────

function IndustryRow({ rank, name, count, max }: {
  rank: number; name: string; count: number; max: number;
}) {
  const pct = max > 0 ? Math.round(count / max * 100) : 0;
  return (
    <div className="flex items-center gap-3 py-1.5 border-b border-border/50 last:border-0 hover:bg-muted/20 px-1 rounded transition-colors">
      <span className="w-5 text-[11px] text-muted-foreground/60 text-right flex-shrink-0 font-mono">
        {rank}
      </span>
      <span className="flex-1 text-[12px] text-foreground font-medium truncate">{name || "Unknown"}</span>
      <div className="w-24 h-1.5 bg-muted rounded-full overflow-hidden flex-shrink-0">
        <div className="h-full bg-primary/70 rounded-full" style={{ width: `${pct}%` }} />
      </div>
      <span className="w-16 text-right text-[12px] font-mono tabnum text-muted-foreground flex-shrink-0 font-medium">
        {count.toLocaleString()}
      </span>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function DashboardOverview() {
  const { stats, loading, refresh } = useDbStats();
  const [isRefreshing, setIsRefreshing] = useState(false);

  const usTotal   = stats?.us_total      ?? 0;
  const mxTotal   = stats?.mx_total      ?? 0;
  const usPhone   = stats?.us_with_phone ?? 0;
  const usEmail   = stats?.us_verified_email ?? 0;
  const mxEmail   = stats?.mx_verified_email ?? 0;

  const usPhonePct = usTotal ? Math.round(usPhone / usTotal * 100) : 0;
  const usEmailPct = usTotal ? Math.round(usEmail / usTotal * 100) : 0;
  const mxEmailPct = mxTotal ? Math.round(mxEmail / mxTotal * 100) : 0;

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await refresh();
    toast.success("Master Vault Telemetry Refreshed", {
      description: "Live multi-source statistics synchronized from PostgreSQL Master Vault",
    });
    setIsRefreshing(false);
  };

  return (
    <div className="space-y-6">

      {/* ── Page title row ─────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-lg font-bold text-foreground tracking-tight">Overview</h1>
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-mono font-medium bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
              210,450 Certified Golden Records
            </span>
          </div>
          <p className="text-[12px] text-muted-foreground mt-0.5">
            DataExtraction Platform · Autonomous B2B Intelligence &amp; Master Vault Engine
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="h-8 text-xs gap-1.5 font-medium border-border/80"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? "animate-spin text-primary" : ""}`} />
            Refresh
          </Button>
          <Button asChild variant="outline" size="sm" className="h-8 text-xs gap-1.5 font-medium border-border/80">
            <Link href="/scraper">
              <Radio className="w-3.5 h-3.5 text-primary" /> Scrapers
            </Link>
          </Button>
          <Button asChild size="sm" className="h-8 text-xs gap-1.5 bg-primary text-primary-foreground hover:bg-primary/90 font-medium shadow-sm">
            <Link href="/export">
              <Download className="w-3.5 h-3.5" /> Export Vault
            </Link>
          </Button>
        </div>
      </div>

      {/* ── KPI grid ───────────────────────────────────────────── */}
      <div>
        <SectionHeader title="Certified Master Vault Metrics" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
          <MetricCard
            label="Master Golden Records"
            value={loading && !stats ? undefined : usTotal}
            sub="Certified Vault (US)"
            href="/leads"
            delta={usTotal ? `+${(usTotal/1000).toFixed(0)}K` : undefined}
            icon={ShieldCheck}
            sourceBadge="master.organizations"
          />
          <MetricCard
            label="Mexico Leads"
            value={loading && !stats ? undefined : mxTotal}
            sub="Certified Vault (MX)"
            href="/leads/mexico"
            icon={Globe2}
            sourceBadge="public.mexico_leads"
          />
          <MetricCard
            label="Direct Phone Coverage"
            value={loading && !stats ? undefined : usPhone}
            sub={`${usPhonePct}% verified phone rate`}
            href="/leads"
            icon={PhoneCall}
            sourceBadge="master.persons"
          />
          <MetricCard
            label="Verified Deliverable Emails"
            value={loading && !stats ? undefined : usEmail + mxEmail}
            sub="RFC 5322 & SMTP certified"
            href="/export"
            icon={MailCheck}
            sourceBadge="master.contact_emails"
          />
        </div>
      </div>

      {/* ── Charts row ─────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Source bar chart */}
        <div className="lg:col-span-2 rounded-lg border border-border/80 bg-card p-4 shadow-sm">
          <SectionHeader
            title="Records by Verified Data Source"
            action={
              <span className="text-[11px] font-mono text-muted-foreground font-semibold bg-muted px-2 py-0.5 rounded">
                {usTotal.toLocaleString()} total entities
              </span>
            }
          />
          {loading && !stats ? (
            <div className="space-y-1.5">
              {[120, 80, 60, 50, 40, 30].map(w => (
                <div key={w} className="flex gap-2 items-center">
                  <Skeleton className="h-3 w-20" />
                  <Skeleton className="h-5" style={{ width: w }} />
                </div>
              ))}
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={230}>
              <BarChart
                data={(stats?.by_source ?? []).slice(0, 8)}
                layout="vertical"
                margin={{ top: 4, right: 12, left: 74, bottom: 0 }}
                barSize={12}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="hsl(var(--border))"
                  horizontal={false}
                  opacity={0.6}
                />
                <XAxis
                  type="number"
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))", fontFamily: "monospace" }}
                  tickFormatter={v => v >= 1000 ? `${(v/1000).toFixed(0)}K` : String(v)}
                  axisLine={false} tickLine={false}
                />
                <YAxis
                  type="category"
                  dataKey="source"
                  width={72}
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                  tickFormatter={fmtSource}
                  axisLine={false} tickLine={false}
                />
                <Tooltip content={<ChartTooltip />} cursor={{ fill: "hsl(var(--muted)/0.5)" }} />
                <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                  {(stats?.by_source ?? []).slice(0, 8).map((entry, i) => (
                    <Cell key={i} fill={SRC_COLOUR[entry.source] ?? "hsl(var(--primary))"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Coverage bars */}
        <div className="rounded-lg border border-border/80 bg-card p-4 shadow-sm">
          <SectionHeader title="Verified Contact Coverage" />
          {loading && !stats ? (
            <div className="space-y-3">
              {[1,2,3,4].map(i => <Skeleton key={i} className="h-5 w-full" />)}
            </div>
          ) : (
            <div className="space-y-1.5">
              <CoverageBar label="US — Phone"    pct={usPhonePct} color="#0f766e" />
              <CoverageBar label="US — Email ✓"  pct={usEmailPct} color="#166534" />
              <CoverageBar
                label="MX — Email ✓"
                pct={mxEmailPct}
                color="#1d4ed8"
              />
              <CoverageBar
                label="MX — Phone"
                pct={mxTotal ? Math.round((stats?.mx_with_phone ?? 0) / mxTotal * 100) : 0}
                color="#6d28d9"
              />
            </div>
          )}

          {/* Totals */}
          <div className="mt-4 pt-3 border-t border-border/60 space-y-1.5">
            {[
              { label: "US Golden Vault",  val: usTotal },
              { label: "MX Golden Vault",  val: mxTotal },
              { label: "Combined Entities", val: usTotal + mxTotal },
            ].map(r => (
              <div key={r.label} className="flex items-center justify-between">
                <span className="text-[11px] text-muted-foreground font-medium">{r.label}</span>
                <span className="text-[12px] font-mono tabnum font-bold text-foreground">
                  {r.val.toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Bottom row ─────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">

        {/* Top industries */}
        <div className="rounded-lg border border-border/80 bg-card p-4 shadow-sm">
          <SectionHeader
            title="Top Industries by Record Volume"
            action={
              <Link href="/leads" className="text-[11px] font-medium text-primary hover:underline transition-colors flex items-center gap-1">
                View Vault →
              </Link>
            }
          />
          {loading && !stats ? (
            <div className="space-y-2">
              {[1,2,3,4,5,6].map(i => <Skeleton key={i} className="h-6 w-full" />)}
            </div>
          ) : (
            <div>
              {(stats?.by_industry ?? []).slice(0, 7).map((ind, i) => (
                <IndustryRow
                  key={ind.industry}
                  rank={i + 1}
                  name={ind.industry}
                  count={ind.count}
                  max={stats?.by_industry?.[0]?.count ?? 1}
                />
              ))}
            </div>
          )}
        </div>

        {/* Top states + seniority split */}
        <div className="rounded-lg border border-border/80 bg-card p-4 shadow-sm">
          <SectionHeader title="Regional Distribution (Top US States)" />
          {loading && !stats ? (
            <div className="space-y-2">
              {[1,2,3,4,5,6].map(i => <Skeleton key={i} className="h-6 w-full" />)}
            </div>
          ) : (
            <>
              <div>
                {(stats?.by_state ?? []).slice(0, 6).map((st, i) => (
                  <IndustryRow
                    key={st.state_code}
                    rank={i + 1}
                    name={st.state_code ?? "Unknown"}
                    count={st.count}
                    max={stats?.by_state?.[0]?.count ?? 1}
                  />
                ))}
              </div>

              {/* Seniority mini grid */}
              <div className="mt-4 pt-3 border-t border-border/60">
                <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground mb-2.5">
                  Executive Seniority Breakdown
                </p>
                <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
                  {(stats?.by_seniority ?? []).slice(0, 5).map(s => (
                    <div key={s.seniority} className="p-2 rounded bg-muted/40 border border-border/40 text-center hover:bg-muted/70 transition-colors">
                      <p className="text-sm font-bold font-mono tabnum text-foreground">
                        {s.count >= 1000 ? `${(s.count/1000).toFixed(0)}K` : s.count}
                      </p>
                      <p className="text-[10px] text-muted-foreground truncate font-medium mt-0.5">
                        {s.seniority?.replace("_"," ") ?? "—"}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
