"use client";
import { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import {
  Radio, Play, Square, RefreshCw, CheckCircle2,
  XCircle, Clock, AlertCircle, Database,
  Globe2, Building2, Shield, FileText,
  Zap, ChevronDown, ChevronUp,
} from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ScraperSource {
  key:          string;
  label:        string;
  description:  string;
  icon:         React.ElementType;
  color:        string;
  requires_key: boolean;
  key_name?:    string;
  est_records:  string;
  country:      "US" | "MX" | "BOTH";
}

interface ScraperStatus {
  key:          string;
  status:       "idle" | "running" | "done" | "error" | "pending_key";
  records:      number;
  last_run?:    string;
  progress?:    number;    // 0–100
  message?:     string;
}

// ── Source definitions ────────────────────────────────────────────────────────

const SOURCES: ScraperSource[] = [
  {
    key: "cms",      label: "CMS NPI",
    description: "8M+ US healthcare providers — doctors, hospitals, clinics with phone numbers.",
    icon: Shield, color: "text-red-500", requires_key: false,
    est_records: "8,000,000", country: "US",
  },
  {
    key: "sec",      label: "SEC EDGAR",
    description: "10,434 US public companies from SEC EDGAR company tickers file.",
    icon: FileText, color: "text-blue-500", requires_key: false,
    est_records: "10,434", country: "US",
  },
  {
    key: "fdic",     label: "FDIC + NCUA",
    description: "All US commercial banks (FDIC) and credit unions (NCUA) with CEO names.",
    icon: Building2, color: "text-amber-500", requires_key: false,
    est_records: "9,000", country: "US",
  },
  {
    key: "usaspending", label: "USASpending.gov",
    description: "Federal contractors from USASpending.gov — company name, NAICS, state.",
    icon: Globe2, color: "text-orange-500", requires_key: false,
    est_records: "100,000", country: "US",
  },
  {
    key: "propublica", label: "ProPublica 990",
    description: "US nonprofits from IRS 990 filings — officers, salaries, addresses.",
    icon: FileText, color: "text-violet-500", requires_key: false,
    est_records: "300,000", country: "US",
  },
  {
    key: "sam",      label: "SAM.gov",
    description: "700K+ registered federal contractors with POC email and phone.",
    icon: Zap, color: "text-green-500", requires_key: true, key_name: "SAM_GOV_API_KEY",
    est_records: "700,000", country: "US",
  },
];

// ── Status helpers ────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: ScraperStatus["status"] }) {
  const map = {
    idle:        { label: "Idle",        color: "bg-muted text-muted-foreground",          icon: Clock },
    running:     { label: "Running",     color: "bg-blue-500/10 text-blue-600 border-blue-200", icon: Radio },
    done:        { label: "Done",        color: "bg-green-500/10 text-green-600 border-green-200", icon: CheckCircle2 },
    error:       { label: "Error",       color: "bg-red-500/10 text-red-600 border-red-200",   icon: XCircle },
    pending_key: { label: "Needs API Key", color: "bg-amber-500/10 text-amber-600 border-amber-200", icon: AlertCircle },
  } as const;
  const m  = map[status] ?? map.idle;
  const Ic = m.icon;
  return (
    <Badge variant="outline" className={`gap-1.5 text-xs ${m.color}`}>
      <Ic className={`w-3 h-3 ${status === "running" ? "animate-pulse" : ""}`} />
      {m.label}
    </Badge>
  );
}

// ── Log viewer ────────────────────────────────────────────────────────────────

function LogViewer({ lines }: { lines: string[] }) {
  if (!lines.length) return null;
  return (
    <div className="mt-3 bg-black/80 rounded-lg p-3 max-h-36 overflow-y-auto font-mono">
      {lines.map((l, i) => (
        <p key={i} className="text-[11px] text-green-400 leading-relaxed">{l}</p>
      ))}
    </div>
  );
}

// ── Single source card ────────────────────────────────────────────────────────

function SourceCard({
  source, status, logs, onRun, onStop,
}: {
  source:  ScraperSource;
  status:  ScraperStatus;
  logs:    string[];
  onRun:   (key: string) => void;
  onStop:  (key: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const isRunning = status.status === "running";
  const Icon = source.icon;

  return (
    <Card className={`transition-all duration-200 ${isRunning ? "border-blue-400/50 shadow-md" : ""}`}>
      <CardContent className="pt-4 pb-3">
        <div className="flex items-start gap-3">
          {/* Icon */}
          <div className={`p-2 rounded-lg bg-muted flex-shrink-0`}>
            <Icon className={`w-4 h-4 ${source.color}`} />
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold text-sm">{source.label}</span>
              <StatusBadge status={status.status} />
              <Badge variant="outline" className="text-[10px]">
                {source.country}
              </Badge>
              {source.requires_key && (
                <Badge variant="outline" className="text-[10px] bg-amber-500/5 text-amber-600 border-amber-200">
                  API Key Required
                </Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-1">{source.description}</p>

            {/* Progress bar when running */}
            {isRunning && status.progress != null && (
              <div className="mt-2 space-y-1">
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>{status.message ?? "Processing..."}</span>
                  <span>{status.progress}%</span>
                </div>
                <Progress value={status.progress} className="h-1.5" />
              </div>
            )}

            {/* Stats row */}
            <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
              <span>Est: <span className="font-medium text-foreground">{source.est_records}</span></span>
              {status.records > 0 && (
                <span>Ingested: <span className="font-medium text-foreground">{status.records.toLocaleString()}</span></span>
              )}
              {status.last_run && (
                <span>Last run: <span className="font-medium text-foreground">
                  {new Date(status.last_run).toLocaleString()}
                </span></span>
              )}
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2 flex-shrink-0">
            {isRunning ? (
              <Button variant="outline" size="sm" className="h-8 text-xs text-destructive border-destructive/30"
                onClick={() => onStop(source.key)}>
                <Square className="w-3 h-3 mr-1" /> Stop
              </Button>
            ) : (
              <Button
                variant={status.status === "done" ? "outline" : "default"}
                size="sm"
                className="h-8 text-xs"
                disabled={status.status === "pending_key"}
                onClick={() => onRun(source.key)}
              >
                {status.status === "done"
                  ? <><RefreshCw className="w-3 h-3 mr-1" /> Re-run</>
                  : <><Play className="w-3 h-3 mr-1" /> Run</>
                }
              </Button>
            )}
            <Button variant="ghost" size="icon" className="h-8 w-8"
              onClick={() => setExpanded(e => !e)}>
              {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </Button>
          </div>
        </div>

        {/* Expanded logs */}
        {expanded && <LogViewer lines={logs} />}
      </CardContent>
    </Card>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

const DEFAULT_STATUSES: Record<string, ScraperStatus> = Object.fromEntries(
  SOURCES.map(s => [s.key, {
    key: s.key,
    status: s.requires_key ? "pending_key" : "idle",
    records: 0,
  }])
);

export function ScraperPanel() {
  const [statuses, setStatuses] = useState<Record<string, ScraperStatus>>(DEFAULT_STATUSES);
  const [logs,     setLogs]     = useState<Record<string, string[]>>({});
  const [polling,  setPolling]  = useState(false);

  // ── Fetch current status from backend ──────────────────────────────────────
  const refreshStatuses = useCallback(async () => {
    try {
      const data = await api.get<{ sources: ScraperStatus[] }>("/scraper/status");
      const map: Record<string, ScraperStatus> = {};
      for (const s of data.sources) map[s.key] = s;
      setStatuses(prev => ({ ...prev, ...map }));
    } catch {
      // backend not yet connected — use mock
    }
  }, []);

  // Poll every 3s when any scraper is running
  useEffect(() => {
    const anyRunning = Object.values(statuses).some(s => s.status === "running");
    if (anyRunning && !polling) {
      setPolling(true);
      const id = setInterval(refreshStatuses, 3000);
      return () => { clearInterval(id); setPolling(false); };
    }
  }, [statuses, polling, refreshStatuses]);

  useEffect(() => { refreshStatuses(); }, [refreshStatuses]);

  // ── Run a source ────────────────────────────────────────────────────────────
  const handleRun = async (key: string) => {
    setStatuses(prev => ({
      ...prev,
      [key]: { ...prev[key], status: "running", progress: 0, message: "Starting..." },
    }));
    setLogs(prev => ({ ...prev, [key]: [`[${new Date().toLocaleTimeString()}] Starting ${key}...`] }));
    try {
      await api.post(`/scraper/run`, { source: key });
      toast.success(`${key} scraper started`);
    } catch (e) {
      setStatuses(prev => ({ ...prev, [key]: { ...prev[key], status: "error", message: String(e) } }));
      toast.error(`Failed to start ${key}`);
    }
  };

  // ── Stop a source ───────────────────────────────────────────────────────────
  const handleStop = async (key: string) => {
    try {
      await api.post(`/scraper/stop`, { source: key });
      setStatuses(prev => ({ ...prev, [key]: { ...prev[key], status: "idle" } }));
      toast.info(`${key} scraper stopped`);
    } catch {
      toast.error(`Failed to stop ${key}`);
    }
  };

  // ── Run all ────────────────────────────────────────────────────────────────
  const handleRunAll = async () => {
    const toRun = SOURCES.filter(s => !s.requires_key).map(s => s.key);
    toast.info(`Starting ${toRun.length} scrapers...`);
    for (const key of toRun) await handleRun(key);
  };

  // ── Summary counts ─────────────────────────────────────────────────────────
  const totalIngested = Object.values(statuses).reduce((sum, s) => sum + s.records, 0);
  const running       = Object.values(statuses).filter(s => s.status === "running").length;
  const done          = Object.values(statuses).filter(s => s.status === "done").length;

  return (
    <div className="space-y-5">
      {/* ── Header ────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg bg-primary/10">
            <Radio className={`w-5 h-5 text-primary ${running > 0 ? "animate-pulse" : ""}`} />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Scraper Control</h1>
            <p className="text-muted-foreground text-sm">
              {running > 0
                ? `${running} scraper${running > 1 ? "s" : ""} running...`
                : "All scrapers idle — ready to run"}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={refreshStatuses}>
            <RefreshCw className="mr-1.5 h-3.5 w-3.5" /> Refresh
          </Button>
          <Button variant="gradient" size="sm" onClick={handleRunAll} disabled={running > 0}>
            <Play className="mr-1.5 h-3.5 w-3.5" /> Run All Free Sources
          </Button>
        </div>
      </div>

      {/* ── Summary stat bar ────────────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: "Running",  value: running,        color: "text-blue-500",  bg: "bg-blue-500/10" },
          { label: "Complete", value: done,            color: "text-green-500", bg: "bg-green-500/10" },
          { label: "Ingested", value: totalIngested,   color: "text-primary",   bg: "bg-primary/10" },
        ].map(s => (
          <Card key={s.label}>
            <CardContent className="pt-4 pb-3 flex items-center gap-3">
              <div className={`p-2 rounded-lg ${s.bg}`}>
                <Database className={`w-4 h-4 ${s.color}`} />
              </div>
              <div>
                <p className={`text-xl font-bold ${s.color}`}>
                  {s.value.toLocaleString()}
                </p>
                <p className="text-xs text-muted-foreground">{s.label}</p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Separator />

      {/* ── Source cards ─────────────────────────────────────────────── */}
      <div>
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">
          Data Sources
        </h2>
        <motion.div
          initial="hidden"
          animate="show"
          variants={{ hidden: {}, show: { transition: { staggerChildren: 0.06 } } }}
          className="space-y-3"
        >
          {SOURCES.map(source => (
            <motion.div
              key={source.key}
              variants={{ hidden: { opacity: 0, y: 8 }, show: { opacity: 1, y: 0 } }}
            >
              <SourceCard
                source={source}
                status={statuses[source.key] ?? { key: source.key, status: "idle", records: 0 }}
                logs={logs[source.key] ?? []}
                onRun={handleRun}
                onStop={handleStop}
              />
            </motion.div>
          ))}
        </motion.div>
      </div>

      {/* ── API key notice ───────────────────────────────────────────── */}
      <Card className="border-amber-200 bg-amber-500/5">
        <CardContent className="pt-4 pb-3 flex items-start gap-3">
          <AlertCircle className="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-amber-700 dark:text-amber-400">
              SAM.gov API Key Required
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              SAM.gov provides 700K+ federal contractors with verified POC email and phone.
              Add <code className="bg-muted px-1 py-0.5 rounded text-[11px]">SAM_GOV_API_KEY</code> to
              your <code className="bg-muted px-1 py-0.5 rounded text-[11px]">.env</code> file to enable it.
              Register free at{" "}
              <a href="https://open.gsa.gov/api/sam/" target="_blank" rel="noreferrer"
                className="text-amber-600 underline">open.gsa.gov/api/sam</a>
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
