"use client";

import { AgentTelemetry } from "../types";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Cpu,
  Database,
  Globe2,
  GitMerge,
  Mail,
  UserCheck,
  ShieldCheck,
  Send,
  Clock,
  Layers,
  Activity,
  AlertTriangle,
  RotateCw,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface AgentStatusGridProps {
  agents: Record<string, AgentTelemetry>;
}

interface DefaultAgentConfig {
  id: string;
  agentNum: number;
  name: string;
  role: string;
  queueName: string;
  icon: React.ElementType;
}

const DEFAULT_AGENTS: DefaultAgentConfig[] = [
  {
    id: "agent_1",
    agentNum: 1,
    name: "Agent 1: Registry Harvester",
    role: "SEC EDGAR, CMS NPI, SAM.gov, FDIC",
    queueName: "registry-harvester",
    icon: Database,
  },
  {
    id: "agent_2",
    agentNum: 2,
    name: "Agent 2: Spatial & Domain",
    role: "OSM Quadtrees, Google Places, Clearbit",
    queueName: "spatial-domain",
    icon: Globe2,
  },
  {
    id: "agent_3",
    agentNum: 3,
    name: "Agent 3: Identity Resolution",
    role: "Splink 5.0, DuckDB Fellegi-Sunter Clusters",
    queueName: "identity-splink",
    icon: GitMerge,
  },
  {
    id: "agent_7",
    agentNum: 7,
    name: "Agent 7: Email Discovery",
    role: "5-Tier RFC 5322 & SMTP Handshake",
    queueName: "email-enrichment",
    icon: Mail,
  },
  {
    id: "agent_4",
    agentNum: 4,
    name: "Agent 4: Executive Discovery",
    role: "Decision Makers & Career Employment Edges",
    queueName: "executive-discovery",
    icon: UserCheck,
  },
  {
    id: "agent_5",
    agentNum: 5,
    name: "Agent 5: Governance & Certification",
    role: "Bayesian Quality, Freshness SLA, Sanctions",
    queueName: "governance-certification",
    icon: ShieldCheck,
  },
  {
    id: "agent_6",
    agentNum: 6,
    name: "Agent 6: CDC, Search & OneReach",
    role: "OpenSearch 2.x Sync & OneReach Delivery",
    queueName: "search-onereach-cdc",
    icon: Send,
  },
];

export function AgentStatusGrid({ agents }: AgentStatusGridProps) {
  const getStatusBadge = (status: AgentTelemetry["status"]) => {
    switch (status) {
      case "RUNNING":
        return (
          <Badge variant="outline" className="gap-1 border-blue-500/40 bg-blue-500/10 text-blue-500 text-[10px] py-0 font-mono animate-pulse">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-500" />
            RUNNING
          </Badge>
        );
      case "COMPLETED":
        return (
          <Badge variant="outline" className="gap-1 border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 text-[10px] py-0 font-mono">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            COMPLETED
          </Badge>
        );
      case "FAILED":
        return (
          <Badge variant="outline" className="gap-1 border-rose-500/40 bg-rose-500/10 text-rose-500 text-[10px] py-0 font-mono">
            <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />
            FAILED
          </Badge>
        );
      case "PAUSED":
        return (
          <Badge variant="outline" className="gap-1 border-amber-500/40 bg-amber-500/10 text-amber-500 text-[10px] py-0 font-mono">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
            PAUSED
          </Badge>
        );
      default:
        return (
          <Badge variant="outline" className="gap-1 border-border/70 text-muted-foreground text-[10px] py-0 font-mono">
            <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />
            IDLE
          </Badge>
        );
    }
  };

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-card p-4 sm:p-5 shadow-xs">
      <div className="flex items-center justify-between border-b border-border/60 pb-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary">
            <Cpu className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold tracking-tight text-foreground">
              Autonomous Agent Fleet Telemetry
            </h3>
            <p className="text-[11px] font-mono text-muted-foreground">
              Real-time monitoring across all 7 distributed worker services
            </p>
          </div>
        </div>

        <Badge variant="outline" className="font-mono text-[10px] text-muted-foreground">
          7 AGENTS CONFIGURED
        </Badge>
      </div>

      {/* Grid of Agent Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3 pt-1">
        {DEFAULT_AGENTS.map((def) => {
          const telemetry: AgentTelemetry = agents[def.id] ?? {
            id: def.id,
            agent_num: def.agentNum,
            name: def.name,
            role: def.role,
            status: "IDLE",
            started_at: null,
            elapsed_seconds: 0,
            progress_pct: 0,
            processed_count: 0,
            failed_count: 0,
            retries_count: 0,
            queue_name: def.queueName,
            current_activity: "Awaiting Trigger",
            current_batch: "batch_00000000",
          };

          const Icon = def.icon;
          const isRunning = telemetry.status === "RUNNING";

          return (
            <div
              key={def.id}
              className={cn(
                "flex flex-col justify-between rounded-lg border p-3.5 bg-background/80 transition-all shadow-xs hover:border-border hover:shadow-sm",
                isRunning && "border-blue-500/50 ring-1 ring-blue-500/30 bg-primary/5"
              )}
            >
              {/* Header */}
              <div>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <div
                      className={cn(
                        "flex h-8 w-8 items-center justify-center rounded-md border flex-shrink-0",
                        isRunning
                          ? "bg-blue-500/10 border-blue-500/30 text-blue-500"
                          : "bg-muted border-border/80 text-muted-foreground"
                      )}
                    >
                      <Icon className="h-4 w-4" />
                    </div>
                    <div>
                      <h4 className="text-xs font-semibold text-foreground leading-tight truncate max-w-[140px]" title={def.name}>
                        {def.name}
                      </h4>
                      <p className="text-[10px] font-mono text-muted-foreground truncate max-w-[140px]" title={def.role}>
                        {def.role}
                      </p>
                    </div>
                  </div>
                  {getStatusBadge(telemetry.status)}
                </div>

                {/* Progress bar */}
                <div className="mt-3 space-y-1">
                  <div className="flex items-center justify-between text-[10px] font-mono">
                    <span className="text-muted-foreground">Progress</span>
                    <span className="font-bold text-foreground">
                      {telemetry.progress_pct.toFixed(0)}%
                    </span>
                  </div>
                  <Progress value={telemetry.progress_pct} className="h-1.5 bg-muted/60" />
                </div>
              </div>

              {/* Metrics Grid */}
              <div className="mt-3 grid grid-cols-3 gap-1.5 rounded-md border border-border/60 bg-muted/20 p-2 text-center text-xs font-mono">
                <div>
                  <span className="text-[9px] uppercase text-muted-foreground/70 block">Processed</span>
                  <span className="font-bold text-foreground tabular-nums">
                    {telemetry.processed_count.toLocaleString()}
                  </span>
                </div>
                <div>
                  <span className="text-[9px] uppercase text-muted-foreground/70 block">Failed</span>
                  <span
                    className={cn(
                      "font-bold tabular-nums",
                      telemetry.failed_count > 0 ? "text-rose-500" : "text-muted-foreground"
                    )}
                  >
                    {telemetry.failed_count}
                  </span>
                </div>
                <div>
                  <span className="text-[9px] uppercase text-muted-foreground/70 block">Retries</span>
                  <span
                    className={cn(
                      "font-bold tabular-nums",
                      telemetry.retries_count > 0 ? "text-amber-500" : "text-muted-foreground"
                    )}
                  >
                    {telemetry.retries_count}
                  </span>
                </div>
              </div>

              {/* Footer Meta */}
              <div className="mt-2.5 pt-2 border-t border-border/50 space-y-1 text-[10px] font-mono">
                <div className="flex items-center justify-between text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <Layers className="h-3 w-3" /> Queue:
                  </span>
                  <span className="text-foreground font-semibold truncate max-w-[130px]" title={telemetry.queue_name}>
                    {telemetry.queue_name}
                  </span>
                </div>

                <div className="flex items-center justify-between text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <Activity className="h-3 w-3" /> Activity:
                  </span>
                  <span className="text-foreground truncate max-w-[130px]" title={telemetry.current_activity}>
                    {telemetry.current_activity}
                  </span>
                </div>

                <div className="flex items-center justify-between text-muted-foreground/60">
                  <span className="flex items-center gap-1">
                    <Clock className="h-3 w-3" /> Elapsed:
                  </span>
                  <span>{telemetry.elapsed_seconds.toFixed(1)}s</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

