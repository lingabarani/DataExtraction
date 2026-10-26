"use client";
import Link from "next/link";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { useDbStats } from "@/hooks/use-leads";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { ArrowUpRight, TrendingUp, Database, Download, Radio } from "lucide-react";

// ── Colour map for sources ────────────────────────────────────────────────────

const SRC_COLOUR: Record<string, string> = {
  CMS_NPI:        "#0f766e",  // teal-700
  SEC_EDGAR:      "#374151",  // gray-700
  FDIC:           "#92400e",  // amber-800
  NCUA:           "#b45309",  // amber-700
  USASPENDING:    "#6d28d9",  // violet-700
  PROPUBLICA_990: "#0e7490",  // cyan-700
  SAM_GOV:        "#166534",  // green-800
  CSV:            "#1d4ed8",  // blue-700
  INTERNAL_JSON:  "#4b5563",  // gray-600
  DB:             "#6b7280",  // gray-500
};

// ── Tiny metric card ──────────────────────────────────────────────────────────

function MetricCard({
  label, value, sub, href, delta,
}: {
  label:  string;
  value:  string | number | undefined;
  sub:    string;
  href:   string;
  delta?: string;
}) {
  return (
    <Link href={href} className="group block">
      <div className="rounded-md border border-border bg-card p-4 hover:border-foreground/20 transition-colors shadow-card">
        <div className="flex items-start justify-between mb-3">
          <span className="text-[11px] font-medium uppercase tracking-widest text-muted-foreground">
            {label}
          </span>
          <ArrowUpRight className="w-3.5 h-3.5 text-muted-foreground/30 group-hover:text-foreground transition-colors" />
        </div>
        {value !== undefined ? (
          <p className="text-2xl font-semibold tabnum tracking-tight text-foreground">
            {typeof value === "number" ? value.toLocaleString() : value}
          </p>
        ) : (
          <Skeleton className="h-8 w-24 mb-0.5" />
        )}
        <div className="flex items-center gap-2 mt-1.5">
          <span className="text-xs text-muted-foreground">{sub}</span>
          {delta && (
            <span className="text-[11px] font-medium text-emerald-600 font-mono">{delta}</span>
          )}
        </div>
      </div>
    </Link>
  );
}

// ── Section header ────────────────────────────────────────────────────────────

function SectionHeader({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h2 className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
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
  return (
    <div className="bg-card border border-border rounded shadow-card-md px-3 py-2 text-xs">
      <p className="font-medium text-foreground mb-0.5">
        {String(label).replace("_NPI","").replace("_EDGAR","").replace("PROPUBLICA_990","ProPublica")}
      </p>
      <p className="tabnum font-mono text-muted-foreground">
        {payload[0].value.toLocaleString()} records
      </p>
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
    .replace("INTERNAL_JSON", "Internal");
}

// ── Coverage row ──────────────────────────────────────────────────────────────

function CoverageBar({ label, pct, color }: { label: string; pct: number; color: string }) {
  return (
    <div className="flex items-center gap-3 py-1.5">
      <span className="w-28 text-[12px] text-muted-foreground flex-shrink-0">{label}</span>
      <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
      <span className="w-10 text-right text-[12px] font-mono tabnum text-foreground">
        {pct}%
      </span>
    </div>
  );
}

// ── Industry table row ────────────────────────────────────────────────────────

function IndustryRow({ rank, name, count, max }: {
  rank: number; name: string; count: number; max: number;
}) {
  const pct = Math.round(count / max * 100);
  return (
    <div className="flex items-center gap-3 py-1.5 border-b border-border/50 last:border-0">
      <span className="w-5 text-[11px] text-muted-foreground/50 text-right flex-shrink-0 font-mono">
        {rank}
      </span>
      <span className="flex-1 text-[12px] text-foreground truncate">{name || "Unknown"}</span>
      <div className="w-24 h-1 bg-muted rounded-full overflow-hidden flex-shrink-0">
        <div className="h-full bg-foreground/20 rounded-full" style={{ width: `${pct}%` }} />
      </div>
      <span className="w-16 text-right text-[12px] font-mono tabnum text-muted-foreground flex-shrink-0">
        {count.toLocaleString()}
      </span>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function DashboardOverview() {
  const { stats, loading } = useDbStats();

  const usTotal   = stats?.us_total      ?? 0;
  const mxTotal   = stats?.mx_total      ?? 0;
  const usPhone   = stats?.us_with_phone ?? 0;
  const usEmail   = stats?.us_verified_email ?? 0;
  const mxEmail   = stats?.mx_verified_email ?? 0;

  const usPhonePct = usTotal ? Math.round(usPhone / usTotal * 100) : 0;
  const usEmailPct = usTotal ? Math.round(usEmail / usTotal * 100) : 0;
  const mxEmailPct = mxTotal ? Math.round(mxEmail / mxTotal * 100) : 0;

  return (
    <div className="space-y-6">

      {/* ── Page title row ─────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[15px] font-semibold text-foreground">Overview</h1>
          <p className="text-[12px] text-muted-foreground mt-0.5">
            DataExtraction Project · US &amp; Mexico B2B intelligence platform
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button asChild variant="outline" size="sm" className="h-8 text-xs gap-1.5">
            <Link href="/scraper">
              <Radio className="w-3.5 h-3.5" /> Scrapers
            </Link>
          </Button>
          <Button asChild size="sm" className="h-8 text-xs gap-1.5 bg-foreground text-background hover:bg-foreground/90">
            <Link href="/export">
              <Download className="w-3.5 h-3.5" /> Export
            </Link>
          </Button>
        </div>
      </div>

      {/* ── KPI grid ───────────────────────────────────────────── */}
      <div>
        <SectionHeader title="Key metrics" />
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <MetricCard
            label="US Leads"
            value={loading ? undefined : usTotal}
            sub="us_leads table"
            href="/leads"
            delta={usTotal ? `+${(usTotal/1000).toFixed(0)}K` : undefined}
          />
          <MetricCard
            label="Mexico Leads"
            value={loading ? undefined : mxTotal}
            sub="mexico_leads table"
            href="/leads/mexico"
          />
          <MetricCard
            label="With Phone"
            value={loading ? undefined : usPhone}
            sub={`${usPhonePct}% of US records`}
            href="/leads"
          />
          <MetricCard
            label="Verified Email"
            value={loading ? undefined : usEmail + mxEmail}
            sub="both markets combined"
            href="/export"
          />
        </div>
      </div>

      {/* ── Charts row ─────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Source bar chart */}
        <div className="lg:col-span-2 rounded-md border border-border bg-card p-4 shadow-card">
          <SectionHeader
            title="Records by data source"
            action={
              <span className="text-[11px] font-mono text-muted-foreground">
                {usTotal.toLocaleString()} total
              </span>
            }
          />
          {loading ? (
            <div className="space-y-1.5">
              {[120, 80, 60, 50, 40, 30].map(w => (
                <div key={w} className="flex gap-2 items-center">
                  <Skeleton className="h-3 w-20" />
                  <Skeleton className="h-5" style={{ width: w }} />
                </div>
              ))}
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart
                data={(stats?.by_source ?? []).slice(0, 8)}
                layout="vertical"
                margin={{ top: 0, right: 6, left: 64, bottom: 0 }}
                barSize={10}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="hsl(var(--border))"
                  horizontal={false}
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
                  width={62}
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                  tickFormatter={fmtSource}
                  axisLine={false} tickLine={false}
                />
                <Tooltip content={<ChartTooltip />} cursor={{ fill: "hsl(var(--muted))" }} />
                <Bar dataKey="count" radius={[0, 3, 3, 0]}>
                  {(stats?.by_source ?? []).slice(0, 8).map((entry, i) => (
                    <Cell key={i} fill={SRC_COLOUR[entry.source] ?? "hsl(var(--muted-foreground))"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Coverage bars */}
        <div className="rounded-md border border-border bg-card p-4 shadow-card">
          <SectionHeader title="Contact coverage" />
          {loading ? (
            <div className="space-y-3">
              {[1,2,3,4].map(i => <Skeleton key={i} className="h-5 w-full" />)}
            </div>
          ) : (
            <div className="space-y-0.5">
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
          <div className="mt-4 pt-3 border-t border-border space-y-1.5">
            {[
              { label: "US total",  val: usTotal },
              { label: "MX total",  val: mxTotal },
              { label: "Combined",  val: usTotal + mxTotal },
            ].map(r => (
              <div key={r.label} className="flex items-center justify-between">
                <span className="text-[11px] text-muted-foreground">{r.label}</span>
                <span className="text-[12px] font-mono tabnum font-medium">
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
        <div className="rounded-md border border-border bg-card p-4 shadow-card">
          <SectionHeader
            title="Top industries"
            action={
              <Link href="/leads" className="text-[11px] text-muted-foreground hover:text-foreground transition-colors">
                View all →
              </Link>
            }
          />
          {loading ? (
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
                  max={stats!.by_industry[0]?.count ?? 1}
                />
              ))}
            </div>
          )}
        </div>

        {/* Top states + seniority split */}
        <div className="rounded-md border border-border bg-card p-4 shadow-card">
          <SectionHeader title="Top US states" />
          {loading ? (
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
                    max={stats!.by_state[0]?.count ?? 1}
                  />
                ))}
              </div>

              {/* Seniority mini grid */}
              <div className="mt-4 pt-3 border-t border-border">
                <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground mb-2">
                  Seniority breakdown
                </p>
                <div className="grid grid-cols-3 gap-2">
                  {(stats?.by_seniority ?? []).slice(0, 6).map(s => (
                    <div key={s.seniority} className="text-center">
                      <p className="text-[13px] font-semibold tabnum">
                        {s.count >= 1000 ? `${(s.count/1000).toFixed(0)}K` : s.count}
                      </p>
                      <p className="text-[10px] text-muted-foreground truncate">
                        {s.seniority?.replace("_","-") ?? "—"}
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
