"use client";

import { WorkflowStatusResponse } from "../types";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import {
  Clock,
  Layers,
  Activity,
  AlertTriangle,
  RotateCw,
  Cpu,
  CheckCircle2,
  ListFilter,
  BarChart2,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface WorkflowStatusPanelProps {
  status: WorkflowStatusResponse | null;
}

export function WorkflowStatusPanel({ status }: WorkflowStatusPanelProps) {
  const currentPhase = status?.current_stage ?? "STANDBY";
  const currentAgent = status?.current_agent ?? "None (Idle)";
  const durationSec = status?.elapsed_seconds ?? 0;
  const currentQueue = status?.current_queue ?? "default";
  const progressPct = status?.progress_pct ?? 0;
  const processed = status?.records_processed ?? 0;
  const waiting = status?.records_waiting ?? 0;
  const failures = status?.failures_count ?? 0;
  const retries = status?.retries_count ?? 0;

  const formatDuration = (totalSeconds: number) => {
    const mins = Math.floor(totalSeconds / 60);
    const secs = Math.floor(totalSeconds % 60);
    if (mins === 0) return `${secs}s`;
    return `${mins}m ${secs}s`;
  };

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border/70 bg-card p-4 sm:p-5 shadow-xs">
      {/* Title & Phase */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-border/60 pb-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-blue-500/10 text-blue-500">
            <Activity className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold tracking-tight text-foreground">
              Temporal Execution Telemetry
            </h3>
            <p className="text-[11px] font-mono text-muted-foreground">
              Workflow ID: {status?.workflow_id ?? "No active execution"}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Badge
            variant="outline"
            className={cn(
              "font-mono text-xs px-2.5 py-0.5",
              status?.status === "RUNNING" && "border-blue-500/40 bg-blue-500/10 text-blue-500 animate-pulse",
              status?.status === "COMPLETED" && "border-emerald-500/40 bg-emerald-500/10 text-emerald-500",
              status?.status === "FAILED" && "border-rose-500/40 bg-rose-500/10 text-rose-500",
              status?.status === "PAUSED" && "border-amber-500/40 bg-amber-500/10 text-amber-500"
            )}
          >
            {status?.status ?? "IDLE"}
          </Badge>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs">
          <span className="font-semibold text-muted-foreground">Pipeline Completion</span>
          <span className="font-mono font-bold text-foreground">{progressPct.toFixed(1)}%</span>
        </div>
        <Progress value={progressPct} className="h-2 bg-muted/60" />
      </div>

      {/* 8 Telemetry Key-Value Tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 pt-1">
        {/* Current Phase */}
        <div className="rounded-lg border border-border/60 bg-background/70 p-2.5">
          <div className="flex items-center gap-1.5 text-muted-foreground text-[10px] uppercase font-semibold">
            <Layers className="h-3 w-3" />
            Current Phase
          </div>
          <div className="mt-1 font-mono text-xs font-bold text-foreground truncate" title={currentPhase}>
            {currentPhase}
          </div>
        </div>

        {/* Current Agent */}
        <div className="rounded-lg border border-border/60 bg-background/70 p-2.5">
          <div className="flex items-center gap-1.5 text-muted-foreground text-[10px] uppercase font-semibold">
            <Cpu className="h-3 w-3" />
            Current Agent
          </div>
          <div className="mt-1 font-mono text-xs font-bold text-foreground truncate" title={currentAgent}>
            {currentAgent}
          </div>
        </div>

        {/* Duration */}
        <div className="rounded-lg border border-border/60 bg-background/70 p-2.5">
          <div className="flex items-center gap-1.5 text-muted-foreground text-[10px] uppercase font-semibold">
            <Clock className="h-3 w-3" />
            Workflow Duration
          </div>
          <div className="mt-1 font-mono text-xs font-bold text-foreground">
            {formatDuration(durationSec)}
          </div>
        </div>

        {/* Queue */}
        <div className="rounded-lg border border-border/60 bg-background/70 p-2.5">
          <div className="flex items-center gap-1.5 text-muted-foreground text-[10px] uppercase font-semibold">
            <ListFilter className="h-3 w-3" />
            Current Queue
          </div>
          <div className="mt-1 font-mono text-xs font-bold text-primary truncate" title={currentQueue}>
            {currentQueue}
          </div>
        </div>

        {/* Records Processed */}
        <div className="rounded-lg border border-border/60 bg-background/70 p-2.5">
          <div className="flex items-center gap-1.5 text-muted-foreground text-[10px] uppercase font-semibold">
            <CheckCircle2 className="h-3 w-3 text-emerald-500" />
            Processed
          </div>
          <div className="mt-1 font-mono text-sm font-bold text-emerald-600 dark:text-emerald-400 tabular-nums">
            {processed.toLocaleString()}
          </div>
        </div>

        {/* Records Waiting */}
        <div className="rounded-lg border border-border/60 bg-background/70 p-2.5">
          <div className="flex items-center gap-1.5 text-muted-foreground text-[10px] uppercase font-semibold">
            <BarChart2 className="h-3 w-3 text-blue-500" />
            In Backlog
          </div>
          <div className="mt-1 font-mono text-sm font-bold text-foreground tabular-nums">
            {waiting.toLocaleString()}
          </div>
        </div>

        {/* Failures */}
        <div className="rounded-lg border border-border/60 bg-background/70 p-2.5">
          <div className="flex items-center gap-1.5 text-muted-foreground text-[10px] uppercase font-semibold">
            <AlertTriangle className="h-3 w-3 text-rose-500" />
            Failures
          </div>
          <div
            className={cn(
              "mt-1 font-mono text-sm font-bold tabular-nums",
              failures > 0 ? "text-rose-500" : "text-foreground"
            )}
          >
            {failures}
          </div>
        </div>

        {/* Retries */}
        <div className="rounded-lg border border-border/60 bg-background/70 p-2.5">
          <div className="flex items-center gap-1.5 text-muted-foreground text-[10px] uppercase font-semibold">
            <RotateCw className="h-3 w-3 text-amber-500" />
            Retries
          </div>
          <div
            className={cn(
              "mt-1 font-mono text-sm font-bold tabular-nums",
              retries > 0 ? "text-amber-500" : "text-foreground"
            )}
          >
            {retries}
          </div>
        </div>
      </div>
    </div>
  );
}

