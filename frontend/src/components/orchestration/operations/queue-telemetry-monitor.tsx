"use client";

import { QueueTelemetry } from "../types";
import { Badge } from "@/components/ui/badge";
import {
  ListFilter,
  Layers,
  Activity,
  AlertCircle,
  Clock,
  Cpu,
  CheckCircle2,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface QueueTelemetryMonitorProps {
  queues: QueueTelemetry[];
  isLoading?: boolean;
}

const DEFAULT_QUEUES: QueueTelemetry[] = [
  {
    id: "registry-ingestion-queue",
    name: "dataextraction-registry-v1",
    agent: "Agent 1: Registry Harvester",
    workers: 8,
    pending: 0,
    running: 0,
    completed: 0,
    failed: 0,
    retrying: 0,
    avg_wait_ms: 0,
    status: "NOMINAL",
  },
  {
    id: "geospatial-domain-queue",
    name: "dataextraction-geospatial-v1",
    agent: "Agent 2: Spatial & Domain Harvester",
    workers: 6,
    pending: 0,
    running: 0,
    completed: 0,
    failed: 0,
    retrying: 0,
    avg_wait_ms: 0,
    status: "NOMINAL",
  },
  {
    id: "identity-clustering-queue",
    name: "dataextraction-identity-v1",
    agent: "Agent 3: Identity & Splink 5.0",
    workers: 4,
    pending: 0,
    running: 0,
    completed: 0,
    failed: 0,
    retrying: 0,
    avg_wait_ms: 0,
    status: "NOMINAL",
  },
  {
    id: "email-enrichment-queue",
    name: "dataextraction-email-enrichment-v1",
    agent: "Agent 7: Email Discovery & Validation",
    workers: 12,
    pending: 0,
    running: 0,
    completed: 0,
    failed: 0,
    retrying: 0,
    avg_wait_ms: 0,
    status: "IDLE",
  },
  {
    id: "executive-contact-queue",
    name: "dataextraction-executive-v1",
    agent: "Agent 4: Executive Discovery",
    workers: 8,
    pending: 0,
    running: 0,
    completed: 0,
    failed: 0,
    retrying: 0,
    avg_wait_ms: 0,
    status: "IDLE",
  },
  {
    id: "governance-quality-queue",
    name: "dataextraction-governance-v1",
    agent: "Agent 5: Governance & Certification",
    workers: 6,
    pending: 0,
    running: 0,
    completed: 0,
    failed: 0,
    retrying: 0,
    avg_wait_ms: 0,
    status: "NOMINAL",
  },
  {
    id: "search-persistence-queue",
    name: "dataextraction-search-v1",
    agent: "Agent 6: OpenSearch CDC & Outbound",
    workers: 10,
    pending: 0,
    running: 0,
    completed: 0,
    failed: 0,
    retrying: 0,
    avg_wait_ms: 0,
    status: "NOMINAL",
  },
];

export function QueueTelemetryMonitor({
  queues = DEFAULT_QUEUES,
  isLoading = false,
}: QueueTelemetryMonitorProps) {
  const displayQueues = queues.length > 0 ? queues : DEFAULT_QUEUES;

  const getStatusBadge = (status: QueueTelemetry["status"]) => {
    switch (status) {
      case "ACTIVE":
        return (
          <Badge variant="outline" className="gap-1 border-blue-500/40 bg-blue-500/10 text-blue-500 text-[10px] py-0 font-mono animate-pulse">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-500" />
            ACTIVE
          </Badge>
        );
      case "PRESSURE":
        return (
          <Badge variant="outline" className="gap-1 border-amber-500/40 bg-amber-500/10 text-amber-500 text-[10px] py-0 font-mono">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
            PRESSURE
          </Badge>
        );
      case "OVERLOADED":
        return (
          <Badge variant="outline" className="gap-1 border-rose-500/40 bg-rose-500/10 text-rose-500 text-[10px] py-0 font-mono">
            <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
            OVERLOADED
          </Badge>
        );
      case "IDLE":
        return (
          <Badge variant="outline" className="gap-1 border-border text-muted-foreground text-[10px] py-0 font-mono">
            <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />
            IDLE
          </Badge>
        );
      default:
        return (
          <Badge variant="outline" className="gap-1 border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 text-[10px] py-0 font-mono">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            NOMINAL
          </Badge>
        );
    }
  };

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border/70 bg-card p-4 sm:p-5 shadow-xs">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-border/60 pb-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary">
            <ListFilter className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold tracking-tight text-foreground">
              Temporal Distributed Task Queue Monitor
            </h3>
            <p className="text-[11px] font-mono text-muted-foreground">
              Real-time worker concurrency, backlog queue depth, and activity dispatch latencies
            </p>
          </div>
        </div>

        <Badge variant="outline" className="font-mono text-xs text-muted-foreground">
          7 ISOLATED TASK QUEUES
        </Badge>
      </div>

      {/* Queue Table */}
      <div className="overflow-x-auto scrollbar-enterprise">
        <table className="w-full text-left text-xs font-mono">
          <thead>
            <tr className="border-b border-border/60 text-[11px] text-muted-foreground/70 uppercase">
              <th className="py-2.5 px-3 font-semibold">Queue & Target Agent</th>
              <th className="py-2.5 px-3 font-semibold text-center">Workers</th>
              <th className="py-2.5 px-3 font-semibold text-right">Backlog Pending</th>
              <th className="py-2.5 px-3 font-semibold text-right">Running</th>
              <th className="py-2.5 px-3 font-semibold text-right">Completed</th>
              <th className="py-2.5 px-3 font-semibold text-right">Avg Wait</th>
              <th className="py-2.5 px-3 font-semibold text-center">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/50 text-[12px]">
            {displayQueues.map((q) => (
              <tr key={q.id} className="hover:bg-muted/30 transition-colors">
                <td className="py-3 px-3">
                  <div className="font-semibold text-foreground">{q.agent}</div>
                  <div className="text-[10px] text-muted-foreground/60">{q.name}</div>
                </td>

                <td className="py-3 px-3 text-center">
                  <span className="inline-flex items-center gap-1 rounded bg-muted/60 px-2 py-0.5 font-bold text-foreground">
                    <Cpu className="h-3 w-3 text-primary" />
                    {q.workers}
                  </span>
                </td>

                <td className="py-3 px-3 text-right">
                  <span
                    className={cn(
                      "font-bold tabular-nums",
                      q.pending > 0 ? "text-amber-500" : "text-muted-foreground"
                    )}
                  >
                    {q.pending.toLocaleString()}
                  </span>
                </td>

                <td className="py-3 px-3 text-right">
                  <span
                    className={cn(
                      "font-bold tabular-nums",
                      q.running > 0 ? "text-blue-500 animate-pulse" : "text-muted-foreground"
                    )}
                  >
                    {q.running}
                  </span>
                </td>

                <td className="py-3 px-3 text-right font-bold text-foreground tabular-nums">
                  {q.completed.toLocaleString()}
                </td>

                <td className="py-3 px-3 text-right text-muted-foreground tabular-nums">
                  {q.avg_wait_ms}ms
                </td>

                <td className="py-3 px-3 text-center">{getStatusBadge(q.status)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

