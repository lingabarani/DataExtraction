"use client";
import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import {
  Copy, Trash2, RefreshCw, ShieldCheck, AlertTriangle,
  CheckCircle2, Loader2, Globe2, Mail, Phone,
  Users, ChevronDown, ChevronUp, Info,
} from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

// ── Types ─────────────────────────────────────────────────────────────────────

interface DupCheck {
  key:           string;
  label:         string;
  description:   string;
  icon:          React.ElementType;
  color:         string;
  field:         string;
}

interface DupResult {
  check:          string;
  table:          "us_leads" | "mexico_leads";
  groups:         number;    // number of groups with duplicates
  extra_rows:     number;    // rows that can be removed
  sample:         DupSample[];
}

interface DupSample {
  value:     string;
  count:     number;
  sources:   string[];
  ids:       string[];
}

interface DupStats {
  us_total:        number;
  mx_total:        number;
  us_duplicates:   number;
  mx_duplicates:   number;
  us_unique:       number;
  mx_unique:       number;
  results:         DupResult[];
  analysed_at:     string;
}

// ── Check definitions ─────────────────────────────────────────────────────────

const CHECKS: DupCheck[] = [
  {
    key:         "email",
    label:       "Duplicate Emails",
    description: "Same email address appearing in multiple rows.",
    icon:        Mail,
    color:       "text-green-500",
    field:       "email",
  },
  {
    key:         "phone",
    label:       "Duplicate Phones",
    description: "Same phone number in multiple rows.",
    icon:        Phone,
    color:       "text-cyan-500",
    field:       "phone",
  },
  {
    key:         "name_company",
    label:       "Same Person + Company",
    description: "Same full_name and company_name combination.",
    icon:        Users,
    color:       "text-violet-500",
    field:       "full_name + company_name",
  },
  {
    key:         "cross_source",
    label:       "Cross-Source Duplicates",
    description: "Same email address ingested from two different API sources.",
    icon:        Copy,
    color:       "text-orange-500",
    field:       "email (multi-source)",
  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function pct(part: number, total: number) {
  if (!total) return 0;
  return Math.round(part / total * 100);
}

function SampleRow({ s }: { s: DupSample }) {
  return (
    <div className="flex items-center gap-3 py-1.5 text-xs border-b last:border-0">
      <span className="flex-1 truncate font-mono text-muted-foreground">{s.value}</span>
      <Badge variant="outline" className="text-[10px] flex-shrink-0">
        ×{s.count}
      </Badge>
      <span className="text-[10px] text-muted-foreground flex-shrink-0">
        {s.sources.join(", ")}
      </span>
    </div>
  );
}

// ── Check card ────────────────────────────────────────────────────────────────

function CheckCard({
  check, result, table, onClean, cleaning,
}: {
  check:    DupCheck;
  result?:  DupResult;
  table:    "us_leads" | "mexico_leads";
  onClean:  (checkKey: string, table: "us_leads" | "mexico_leads") => void;
  cleaning: string | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const Icon       = check.icon;
  const isRunning  = cleaning === `${check.key}_${table}`;
  const extra      = result?.extra_rows ?? 0;
  const groups     = result?.groups     ?? 0;

  return (
    <Card className={extra > 0 ? "border-amber-200/60" : ""}>
      <CardContent className="pt-4 pb-3">
        <div className="flex items-start gap-3">
          {/* Icon */}
          <div className="p-2 rounded-lg bg-muted flex-shrink-0">
            <Icon className={`w-4 h-4 ${check.color}`} />
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold text-sm">{check.label}</span>
              {extra > 0 ? (
                <Badge variant="outline" className="text-[10px] bg-amber-500/10 text-amber-600 border-amber-200 gap-1">
                  <AlertTriangle className="w-2.5 h-2.5" />
                  {extra.toLocaleString()} removable
                </Badge>
              ) : result ? (
                <Badge variant="outline" className="text-[10px] bg-green-500/10 text-green-600 border-green-200 gap-1">
                  <CheckCircle2 className="w-2.5 h-2.5" /> Clean
                </Badge>
              ) : null}
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">{check.description}</p>
            {result && (
              <p className="text-xs text-muted-foreground mt-1">
                Field: <code className="bg-muted px-1 rounded text-[11px]">{check.field}</code>
                {groups > 0 && <> · {groups.toLocaleString()} duplicate groups</>}
              </p>
            )}
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2 flex-shrink-0">
            {extra > 0 && (
              <Button
                variant="destructive"
                size="sm"
                className="h-8 text-xs"
                disabled={isRunning}
                onClick={() => onClean(check.key, table)}
              >
                {isRunning
                  ? <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                  : <Trash2 className="w-3 h-3 mr-1" />
                }
                Remove {extra.toLocaleString()}
              </Button>
            )}
            {result?.sample && result.sample.length > 0 && (
              <Button
                variant="ghost" size="icon" className="h-8 w-8"
                onClick={() => setExpanded(e => !e)}
              >
                {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              </Button>
            )}
          </div>
        </div>

        {/* Sample rows */}
        <AnimatePresence>
          {expanded && result?.sample && result.sample.length > 0 && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-3 overflow-hidden"
            >
              <div className="bg-muted/30 rounded-lg p-3">
                <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide mb-2">
                  Top {result.sample.length} duplicates
                </p>
                {result.sample.map((s, i) => <SampleRow key={i} s={s} />)}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </CardContent>
    </Card>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function DuplicatesManager() {
  const [stats,     setStats]     = useState<DupStats | null>(null);
  const [loading,   setLoading]   = useState(false);
  const [cleaning,  setCleaning]  = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"us_leads" | "mexico_leads">("us_leads");

  // ── Fetch analysis ────────────────────────────────────────────────────────
  const fetchStats = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get<DupStats>("/duplicates/analyse");
      setStats(data);
    } catch {
      // Backend not connected — use mock data for preview
      setStats({
        us_total:      906579,
        mx_total:       50208,
        us_duplicates:   1842,
        mx_duplicates:    312,
        us_unique:     904737,
        mx_unique:      49896,
        analysed_at:   new Date().toISOString(),
        results: [
          { check: "email",        table: "us_leads",     groups: 156,  extra_rows: 312,  sample: [
            { value: "james.wilson@niagarauniversity.com", count: 2, sources: ["DB","INTERNAL_JSON"], ids: [] },
            { value: "robert.johnson@universityofmiss.com", count: 2, sources: ["DB","CSV"], ids: [] },
          ]},
          { check: "phone",        table: "us_leads",     groups: 387,  extra_rows: 847,  sample: [
            { value: "+16859913644", count: 3, sources: ["CMS_NPI","DB","INTERNAL_JSON"], ids: [] },
          ]},
          { check: "name_company", table: "us_leads",     groups: 234,  extra_rows: 458,  sample: [] },
          { check: "cross_source", table: "us_leads",     groups: 89,   extra_rows: 225,  sample: [] },
          { check: "email",        table: "mexico_leads", groups: 42,   extra_rows: 84,   sample: [
            { value: "lflores@transformadoranaci.mx", count: 2, sources: ["CSV","MEXICO_JSON"], ids: [] },
          ]},
          { check: "phone",        table: "mexico_leads", groups: 68,   extra_rows: 136,  sample: [] },
          { check: "name_company", table: "mexico_leads", groups: 31,   extra_rows: 46,   sample: [] },
          { check: "cross_source", table: "mexico_leads", groups: 12,   extra_rows: 24,   sample: [] },
        ],
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchStats(); }, [fetchStats]);

  // ── Clean duplicates ──────────────────────────────────────────────────────
  const handleClean = async (checkKey: string, table: "us_leads" | "mexico_leads") => {
    const confirmMsg = `Remove duplicate ${checkKey} records from ${table}? This keeps the highest-scored record in each group.`;
    if (!confirm(confirmMsg)) return;

    const runKey = `${checkKey}_${table}`;
    setCleaning(runKey);
    try {
      const res = await api.post<{ removed: number }>("/duplicates/clean", { check: checkKey, table });
      toast.success(`Removed ${res.removed.toLocaleString()} duplicate records from ${table}`);
      await fetchStats();
    } catch (e) {
      toast.error(`Clean failed: ${e}`);
    } finally {
      setCleaning(null);
    }
  };

  // ── Clean all ─────────────────────────────────────────────────────────────
  const handleCleanAll = async () => {
    if (!confirm("Remove ALL detected duplicates from both tables? This keeps the highest-scored record in each group.")) return;
    try {
      const res = await api.post<{ removed: number }>("/duplicates/clean-all", {});
      toast.success(`Removed ${res.removed.toLocaleString()} total duplicate records`);
      await fetchStats();
    } catch (e) {
      toast.error(`Clean all failed: ${e}`);
    }
  };

  // ── Derived data ──────────────────────────────────────────────────────────
  const currentResults = stats?.results.filter(r => r.table === activeTab) ?? [];
  const totalRemovable = currentResults.reduce((sum, r) => sum + r.extra_rows, 0);
  const totalRows      = activeTab === "us_leads" ? (stats?.us_total ?? 0) : (stats?.mx_total ?? 0);
  const totalDups      = activeTab === "us_leads" ? (stats?.us_duplicates ?? 0) : (stats?.mx_duplicates ?? 0);
  const uniqueRows     = activeTab === "us_leads" ? (stats?.us_unique ?? 0) : (stats?.mx_unique ?? 0);
  const dupPct         = pct(totalDups, totalRows);

  return (
    <div className="space-y-5">

      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-amber-500/10">
            <Copy className="w-5 h-5 text-amber-500" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Duplicate Manager</h1>
            <p className="text-muted-foreground text-sm">
              Find and remove duplicate records from us_leads and mexico_leads.
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={fetchStats} disabled={loading}>
            {loading
              ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              : <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
            }
            Refresh Analysis
          </Button>
          {totalRemovable > 0 && (
            <Button variant="destructive" size="sm" onClick={handleCleanAll}>
              <Trash2 className="mr-1.5 h-3.5 w-3.5" />
              Clean All Duplicates
            </Button>
          )}
        </div>
      </div>

      {/* ── Table tabs ─────────────────────────────────────────────── */}
      <div className="flex gap-2">
        {(["us_leads","mexico_leads"] as const).map(t => (
          <button
            key={t}
            onClick={() => setActiveTab(t)}
            className={`
              flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border transition-all
              ${activeTab === t
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-muted/30 text-muted-foreground border-border hover:bg-muted"
              }
            `}
          >
            <Globe2 className={`w-3.5 h-3.5 ${
              t === "us_leads" ? "text-blue-400" : "text-green-400"
            } ${activeTab === t ? "opacity-100" : ""}`} />
            {t === "us_leads" ? "US Leads" : "Mexico Leads"}
            {(() => {
              const dups = t === "us_leads" ? (stats?.us_duplicates ?? 0) : (stats?.mx_duplicates ?? 0);
              return dups > 0 ? (
                <Badge className="ml-1 bg-amber-500/20 text-amber-600 border-0 text-[10px] py-0">
                  {dups.toLocaleString()}
                </Badge>
              ) : null;
            })()}
          </button>
        ))}
      </div>

      {loading && !stats ? (
        <div className="flex items-center justify-center py-20 gap-3 text-muted-foreground">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span className="text-sm">Analysing duplicates...</span>
        </div>
      ) : (
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-4"
        >
          {/* ── Summary cards ─────────────────────────────────────── */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: "Total Rows",      value: totalRows,      color: "text-foreground",     icon: Database2 },
              { label: "Duplicates Found",value: totalDups,      color: "text-amber-500",       icon: AlertTriangle },
              { label: "Unique Records",  value: uniqueRows,     color: "text-green-500",       icon: CheckCircle2 },
              { label: "Removable Rows",  value: totalRemovable, color: "text-destructive",     icon: Trash2 },
            ].map(s => (
              <Card key={s.label}>
                <CardContent className="pt-4 pb-3">
                  <div className="flex items-start justify-between">
                    <div>
                      <p className={`text-xl font-bold ${s.color}`}>
                        {s.value.toLocaleString()}
                      </p>
                      <p className="text-xs text-muted-foreground mt-0.5">{s.label}</p>
                    </div>
                    <s.icon className={`w-4 h-4 ${s.color} mt-1 flex-shrink-0`} />
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* ── Overall cleanliness bar ────────────────────────────── */}
          <Card>
            <CardContent className="pt-4 pb-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium">Data Cleanliness</span>
                <span className="text-sm font-bold text-green-600">
                  {100 - dupPct}% unique
                </span>
              </div>
              <Progress value={100 - dupPct} className="h-2.5" />
              <div className="flex justify-between text-xs text-muted-foreground mt-1.5">
                <span>{uniqueRows.toLocaleString()} unique records</span>
                <span>{totalDups.toLocaleString()} duplicates ({dupPct}%)</span>
              </div>
            </CardContent>
          </Card>

          <Separator />

          {/* ── Check cards ───────────────────────────────────────── */}
          <div>
            <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
              Duplicate Checks — {activeTab}
            </h2>
            <div className="space-y-3">
              {CHECKS.map(check => {
                const result = currentResults.find(r => r.check === check.key);
                return (
                  <CheckCard
                    key={check.key}
                    check={check}
                    result={result}
                    table={activeTab}
                    onClean={handleClean}
                    cleaning={cleaning}
                  />
                );
              })}
            </div>
          </div>

          {/* ── Info box ──────────────────────────────────────────── */}
          <Card className="border-blue-200/50 bg-blue-500/5">
            <CardContent className="pt-3 pb-3 flex items-start gap-3">
              <Info className="w-4 h-4 text-blue-500 flex-shrink-0 mt-0.5" />
              <div className="space-y-1">
                <p className="text-sm font-medium text-blue-700 dark:text-blue-400">
                  Safe deduplication — keeps best record
                </p>
                <p className="text-xs text-muted-foreground">
                  The Remove button keeps the record with the highest{" "}
                  <code className="bg-muted px-1 rounded text-[11px]">lead_score</code> within
                  each duplicate group and deletes the rest. This is irreversible — export your
                  data before cleaning if needed.
                </p>
                <p className="text-xs text-muted-foreground">
                  Duplicate logic:{" "}
                  <code className="bg-muted px-1 rounded text-[11px]">
                    PARTITION BY COALESCE(email, id), UPPER(full_name), UPPER(company_name)
                  </code>
                </p>
              </div>
            </CardContent>
          </Card>

          {/* ── Analysis timestamp ────────────────────────────────── */}
          {stats?.analysed_at && (
            <p className="text-xs text-center text-muted-foreground/60">
              Last analysed: {new Date(stats.analysed_at).toLocaleString()}
            </p>
          )}
        </motion.div>
      )}
    </div>
  );
}

// Inline icon alias
function Database2({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M21 12c0 1.657-4.03 3-9 3S3 13.657 3 12" />
      <path d="M3 5v14c0 1.657 4.03 3 9 3s9-1.343 9-3V5" />
    </svg>
  );
}
