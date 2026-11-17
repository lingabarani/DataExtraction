"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Loader2, Play, RefreshCw } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";

interface ExecutedAction {
  workflow: string;
  params: Record<string, unknown>;
  reason?: string;
  started?: boolean;
  workflow_id?: string;
}
interface RejectedAction {
  workflow: string;
  reason?: string;
  rejected_because: string;
}
interface Decision {
  id: number;
  ts: string;
  mode: "llm" | "fallback";
  dry_run: boolean;
  llm_provider: string | null;
  llm_model: string | null;
  plan: { summary?: string; actions: { workflow: string }[] };
  executed: ExecutedAction[];
  rejected: RejectedAction[];
  note: string | null;
}
interface PlannerConfig {
  config: Record<string, unknown>;
  dry_run_default: boolean;
  allowed_workflows: Record<string, { queue: string; description: string; parameters: string[] }>;
}
interface LlmStatus {
  provider: string;
  budget: { daily_token_budget: number; tokens_used_today: number | null; unlimited: boolean };
}

export function AutonomyPanel() {
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [cfg, setCfg] = useState<PlannerConfig | null>(null);
  const [llm, setLlm] = useState<LlmStatus | null>(null);
  const [dryRun, setDryRun] = useState(true);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [d, c, s] = await Promise.all([
        api.get<{ decisions: Decision[] }>("/v1/planner/decisions?limit=30"),
        api.get<PlannerConfig>("/v1/planner/config"),
        api.get<LlmStatus>("/v1/llm/status").catch(() => null),
      ]);
      setDecisions(d.decisions);
      setCfg(c);
      setLlm(s);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to load planner data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function runNow() {
    setRunning(true);
    try {
      const res = await api.post<{ executed: ExecutedAction[]; rejected: unknown[]; mode: string }>(
        "/v1/planner/run",
        { dry_run: dryRun },
        { timeoutMs: 60000 },
      );
      const started = res.executed.filter((e) => e.started).length;
      toast.success(
        dryRun
          ? `Dry run: ${res.executed.length} action(s) planned, nothing started (${res.mode})`
          : `Planner started ${started} workflow(s) (${res.mode})`,
      );
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Planner run failed");
    } finally {
      setRunning(false);
    }
  }

  const used = llm?.budget.tokens_used_today ?? null;
  const budget = llm?.budget.daily_token_budget ?? 0;
  const pct = used !== null && budget > 0 ? Math.min(100, Math.round((used / budget) * 100)) : null;

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Autonomy</h1>
          <p className="text-sm text-muted-foreground">
            The planner checks the platform every 15 minutes and starts allowed workflows on its own.
            Every decision is recorded below.
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <input id="dry" type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
            <Label htmlFor="dry">Dry run (start nothing)</Label>
          </div>
          <Button onClick={() => void runNow()} disabled={running}>
            {running ? <Loader2 className="animate-spin" /> : <Play />} Run now
          </Button>
          <Button variant="outline" onClick={() => void load()} disabled={loading}>
            {loading ? <Loader2 className="animate-spin" /> : <RefreshCw />} Refresh
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Mode</CardTitle>
            <CardDescription>Set PLANNER_DRY_RUN=false in .env for scheduled runs to start workflows.</CardDescription>
          </CardHeader>
          <CardContent>
            <Badge variant={cfg?.dry_run_default ? "secondary" : "default"}>
              {cfg ? (cfg.dry_run_default ? "Scheduled runs: dry run" : "Scheduled runs: live") : "..."}
            </Badge>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">LLM tokens today</CardTitle>
            <CardDescription>Provider: {llm?.provider ?? "unknown"}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-semibold">{used ?? "n/a"}</div>
            <div className="text-xs text-muted-foreground">
              {llm?.budget.unlimited ? "no daily limit" : `of ${budget}`}
            </div>
            {pct !== null && (
              <div className="mt-2 h-2 w-full rounded bg-muted">
                <div className="h-2 rounded bg-primary" style={{ width: `${pct}%` }} />
              </div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Allowed workflows</CardTitle>
            <CardDescription>The planner can start only these.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {cfg && Object.keys(cfg.allowed_workflows).map((w) => (
              <Badge key={w} variant="outline">{w.replace("Workflow", "")}</Badge>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Decision history</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4" data-testid="decision-list">
          {decisions.length === 0 && (
            <p className="text-sm text-muted-foreground">No decisions yet. Click &quot;Run now&quot; with dry run on.</p>
          )}
          {decisions.map((d) => (
            <div key={d.id} className="rounded-md border p-3 text-sm">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs text-muted-foreground">#{d.id}</span>
                <span>{new Date(d.ts).toLocaleString()}</span>
                <Badge variant={d.mode === "llm" ? "default" : "secondary"}>
                  {d.mode === "llm" ? `AI (${d.llm_provider ?? "llm"})` : "rules"}
                </Badge>
                {d.dry_run && <Badge variant="outline">dry run</Badge>}
              </div>
              {d.note && <p className="mb-2 text-xs text-muted-foreground">{d.note}</p>}
              {d.executed.length === 0 && d.rejected.length === 0 && (
                <p className="text-muted-foreground">Nothing needed.</p>
              )}
              <ul className="space-y-1">
                {d.executed.map((a, i) => (
                  <li key={`e${i}`}>
                    <Badge variant={a.started ? "default" : "secondary"}>{a.started ? "started" : "planned"}</Badge>{" "}
                    <b>{a.workflow}</b> <span className="text-muted-foreground">{a.reason}</span>
                  </li>
                ))}
                {d.rejected.map((a, i) => (
                  <li key={`r${i}`}>
                    <Badge variant="destructive">blocked</Badge> <b>{a.workflow}</b>{" "}
                    <span className="text-muted-foreground">{a.rejected_because}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
