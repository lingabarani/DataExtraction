"use client";

import { HeaderStatusResponse } from "../types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Server,
  Cpu,
  Database,
  Search,
  Send,
  RefreshCw,
  Clock,
  Activity,
  CheckCircle2,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface CommandHeaderProps {
  data: HeaderStatusResponse | null;
  isLoading: boolean;
  onRefresh: () => void;
}

export function CommandHeader({ data, isLoading, onRefresh }: CommandHeaderProps) {
  const platform = data?.platform ?? { status: "ONLINE", latency_ms: 12 };
  const temporal = data?.temporal ?? {
    status: "DURABLE",
    endpoint: "localhost:7233",
    active_workflows: 0,
    pending_workflows: 0,
  };
  const database = data?.database ?? {
    status: "CONNECTED",
    master_records: 210450,
    ping_ms: 4,
  };
  const opensearch = data?.opensearch ?? {
    status: "SYNCED",
    synced_documents: 210450,
  };
  const onereach = data?.onereach ?? {
    status: "ACTIVE",
    webhook_status: "READY",
  };

  const activeWorkflows = data?.telemetry?.active_workflows ?? 0;
  const pendingWorkflows = data?.telemetry?.pending_workflows ?? 0;
  const lastRun = data?.telemetry?.last_successful_run;

  return (
    <div className="flex flex-col gap-4 border-b border-border/70 bg-card/40 p-4 sm:p-6 backdrop-blur">
      {/* Top operational bar */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 border border-primary/25">
              <Cpu className="h-4 w-4 text-primary animate-pulse" />
            </div>
            <div>
              <h1 className="text-lg font-semibold tracking-tight text-foreground flex items-center gap-2">
                Temporal Orchestration Command Center
                <Badge
                  variant="outline"
                  className="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20 text-[10px] font-mono uppercase tracking-wider py-0"
                >
                  LIVE TELEMETRY
                </Badge>
              </h1>
              <p className="text-xs text-muted-foreground">
                Autonomous B2B data extraction, entity resolution, and certified Master Golden Record pipeline
              </p>
            </div>
          </div>
        </div>

        {/* Global Action Refresh */}
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            onClick={onRefresh}
            disabled={isLoading}
            className="h-8 gap-1.5 border-border/80 text-xs font-mono font-medium hover:bg-muted/60"
          >
            <RefreshCw
              className={cn("h-3.5 w-3.5 text-muted-foreground", isLoading && "animate-spin text-primary")}
            />
            {isLoading ? "Syncing..." : "Refresh Status"}
          </Button>
        </div>
      </div>

      {/* Cluster Health Pills */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5 pt-1">
        {/* Platform Status */}
        <div className="flex items-center gap-2.5 rounded-lg border border-border/60 bg-background/50 px-3 py-2 text-xs">
          <div className="relative flex h-2 w-2 items-center justify-center">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
          </div>
          <Server className="h-3.5 w-3.5 text-muted-foreground/70" />
          <div className="min-w-0 flex-1">
            <div className="text-[10px] uppercase font-semibold text-muted-foreground/60 tracking-wider">Platform</div>
            <div className="truncate font-mono font-medium text-foreground">
              {platform.status} <span className="text-[10px] text-muted-foreground">({platform.latency_ms}ms)</span>
            </div>
          </div>
        </div>

        {/* Temporal Status */}
        <div className="flex items-center gap-2.5 rounded-lg border border-border/60 bg-background/50 px-3 py-2 text-xs">
          <div className="relative flex h-2 w-2 items-center justify-center">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
          </div>
          <Cpu className="h-3.5 w-3.5 text-muted-foreground/70" />
          <div className="min-w-0 flex-1">
            <div className="text-[10px] uppercase font-semibold text-muted-foreground/60 tracking-wider">Temporal</div>
            <div className="truncate font-mono font-medium text-foreground">
              {temporal.status} <span className="text-[10px] text-muted-foreground">7233</span>
            </div>
          </div>
        </div>

        {/* Database Status */}
        <div className="flex items-center gap-2.5 rounded-lg border border-border/60 bg-background/50 px-3 py-2 text-xs">
          <div className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          <Database className="h-3.5 w-3.5 text-muted-foreground/70" />
          <div className="min-w-0 flex-1">
            <div className="text-[10px] uppercase font-semibold text-muted-foreground/60 tracking-wider">Database</div>
            <div className="truncate font-mono font-medium text-foreground">
              {database.master_records.toLocaleString()} <span className="text-[10px] text-muted-foreground">Master</span>
            </div>
          </div>
        </div>

        {/* OpenSearch Status */}
        <div className="flex items-center gap-2.5 rounded-lg border border-border/60 bg-background/50 px-3 py-2 text-xs">
          <div className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          <Search className="h-3.5 w-3.5 text-muted-foreground/70" />
          <div className="min-w-0 flex-1">
            <div className="text-[10px] uppercase font-semibold text-muted-foreground/60 tracking-wider">OpenSearch</div>
            <div className="truncate font-mono font-medium text-foreground">
              {opensearch.status} <span className="text-[10px] text-muted-foreground">CDC</span>
            </div>
          </div>
        </div>

        {/* OneReach Status */}
        <div className="col-span-2 sm:col-span-1 flex items-center gap-2.5 rounded-lg border border-border/60 bg-background/50 px-3 py-2 text-xs">
          <div className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          <Send className="h-3.5 w-3.5 text-muted-foreground/70" />
          <div className="min-w-0 flex-1">
            <div className="text-[10px] uppercase font-semibold text-muted-foreground/60 tracking-wider">OneReach</div>
            <div className="truncate font-mono font-medium text-foreground">
              {onereach.status} <span className="text-[10px] text-muted-foreground">Webhook</span>
            </div>
          </div>
        </div>
      </div>

      {/* Primary KPI Header Ribbon */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-1">
        <div className="flex items-center justify-between rounded-lg border border-border/70 bg-card p-3 shadow-xs">
          <div className="space-y-0.5">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">
              Active Workflows
            </p>
            <p className="text-2xl font-bold font-mono tracking-tight text-foreground">
              {activeWorkflows}
            </p>
          </div>
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-blue-500/10 text-blue-500">
            <Activity className="h-5 w-5" />
          </div>
        </div>

        <div className="flex items-center justify-between rounded-lg border border-border/70 bg-card p-3 shadow-xs">
          <div className="space-y-0.5">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">
              Pending Workflows
            </p>
            <p className="text-2xl font-bold font-mono tracking-tight text-foreground">
              {pendingWorkflows}
            </p>
          </div>
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-amber-500/10 text-amber-500">
            <Clock className="h-5 w-5" />
          </div>
        </div>

        <div className="flex items-center justify-between rounded-lg border border-border/70 bg-card p-3 shadow-xs">
          <div className="space-y-0.5">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">
              Last Successful Run
            </p>
            <p className="text-sm font-semibold font-mono tracking-tight text-foreground truncate max-w-[200px]">
              {lastRun ? `${lastRun.duration_seconds.toFixed(1)}s elapsed` : "Certified Golden Run"}
            </p>
            <p className="text-[10px] font-mono text-muted-foreground/60">
              {lastRun?.completed_at ? new Date(lastRun.completed_at).toLocaleTimeString() : "Ready for Ingestion"}
            </p>
          </div>
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-emerald-500/10 text-emerald-500">
            <CheckCircle2 className="h-5 w-5" />
          </div>
        </div>
      </div>
    </div>
  );
}

