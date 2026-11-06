"use client";

import { motion } from "framer-motion";
import { StageTelemetry } from "../types";
import { Badge } from "@/components/ui/badge";
import {
  Database,
  Globe2,
  GitMerge,
  Mail,
  UserCheck,
  ShieldCheck,
  Award,
  Send,
  CheckCircle2,
  Clock,
  AlertCircle,
  Loader2,
  ArrowRight,
  ChevronDown,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface PipelineDAGViewProps {
  stages: Record<string, StageTelemetry>;
  selectedStageId: string | null;
  onSelectStage: (stageId: string) => void;
}

interface DAGNodeDef {
  id: string;
  stageKey: string;
  name: string;
  agentLabel: string;
  agentNum: number;
  outputLayer: string;
  icon: React.ElementType;
  description: string;
}

const DAG_NODES: DAGNodeDef[] = [
  {
    id: "REGISTRY_INGESTION",
    stageKey: "REGISTRY_INGESTION",
    name: "Registry Harvester",
    agentLabel: "Agent 1",
    agentNum: 1,
    outputLayer: "staging_companies",
    icon: Database,
    description: "SEC EDGAR, CMS NPI, SAM.gov, FDIC",
  },
  {
    id: "GEOSPATIAL_STANDARDIZATION",
    stageKey: "GEOSPATIAL_STANDARDIZATION",
    name: "Spatial & Domain Harvester",
    agentLabel: "Agent 2",
    agentNum: 2,
    outputLayer: "staging.locations",
    icon: Globe2,
    description: "OSM Quadtrees, Google Places, Logos",
  },
  {
    id: "IDENTITY_RESOLUTION",
    stageKey: "IDENTITY_RESOLUTION",
    name: "Identity Resolution",
    agentLabel: "Agent 3",
    agentNum: 3,
    outputLayer: "working_organizations",
    icon: GitMerge,
    description: "Splink 5.0, DuckDB Fellegi-Sunter",
  },
  {
    id: "EMAIL_ENRICHMENT",
    stageKey: "EMAIL_ENRICHMENT",
    name: "Email Discovery & 5-Tier",
    agentLabel: "Agent 7",
    agentNum: 7,
    outputLayer: "working_emails",
    icon: Mail,
    description: "RFC 5322, MX DNS, SMTP Handshake",
  },
  {
    id: "EXECUTIVE_DISCOVERY",
    stageKey: "EXECUTIVE_DISCOVERY",
    name: "Executive Discovery",
    agentLabel: "Agent 4",
    agentNum: 4,
    outputLayer: "working_persons",
    icon: UserCheck,
    description: "Decision Makers, Career Edges",
  },
  {
    id: "GOVERNANCE_CERTIFICATION",
    stageKey: "GOVERNANCE_CERTIFICATION",
    name: "Governance & Certification",
    agentLabel: "Agent 5",
    agentNum: 5,
    outputLayer: "certification_scores",
    icon: ShieldCheck,
    description: "Completeness, Freshness, Sanctions",
  },
  {
    id: "PROMOTION_GATE",
    stageKey: "PROMOTION_GATE",
    name: "PROMOTION GATE",
    agentLabel: "Promotion Gate",
    agentNum: 0,
    outputLayer: "master_dataextraction",
    icon: Award,
    description: "Atomic Certified Golden Promotion",
  },
  {
    id: "POST_MASTER_OUTBOUND",
    stageKey: "POST_MASTER_OUTBOUND",
    name: "Search, CDC & OneReach",
    agentLabel: "Agent 6",
    agentNum: 6,
    outputLayer: "OpenSearch & OneReach",
    icon: Send,
    description: "OpenSearch 2.x CDC + Webhooks",
  },
];

export function PipelineDAGView({
  stages,
  selectedStageId,
  onSelectStage,
}: PipelineDAGViewProps) {
  const getStageStatus = (stageKey: string): StageTelemetry["status"] => {
    return stages[stageKey]?.status ?? "PENDING";
  };

  const getStatusBadge = (status: StageTelemetry["status"]) => {
    switch (status) {
      case "COMPLETED":
        return (
          <Badge variant="outline" className="gap-1 border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 text-[10px] py-0 font-mono">
            <CheckCircle2 className="h-3 w-3" />
            COMPLETED
          </Badge>
        );
      case "RUNNING":
        return (
          <Badge variant="outline" className="gap-1 border-blue-500/40 bg-blue-500/15 text-blue-500 text-[10px] py-0 font-mono animate-pulse">
            <Loader2 className="h-3 w-3 animate-spin" />
            RUNNING
          </Badge>
        );
      case "FAILED":
        return (
          <Badge variant="outline" className="gap-1 border-rose-500/40 bg-rose-500/10 text-rose-500 text-[10px] py-0 font-mono">
            <AlertCircle className="h-3 w-3" />
            FAILED
          </Badge>
        );
      case "SKIPPED":
        return (
          <Badge variant="outline" className="border-border text-muted-foreground text-[10px] py-0 font-mono">
            SKIPPED
          </Badge>
        );
      default:
        return (
          <Badge variant="outline" className="border-border/60 text-muted-foreground/50 text-[10px] py-0 font-mono">
            PENDING
          </Badge>
        );
    }
  };

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-card p-4 sm:p-5 shadow-xs">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded bg-primary/10 text-primary">
            <GitMerge className="h-3.5 w-3.5" />
          </div>
          <h2 className="text-sm font-semibold tracking-tight text-foreground">
            Topological Pipeline Directed Acyclic Graph (DAG)
          </h2>
          <span className="text-[11px] font-mono text-muted-foreground">
            8 Sequential Certified Vault Stages
          </span>
        </div>
        <div className="text-[11px] font-mono text-muted-foreground">
          Click any stage node to inspect activity telemetry
        </div>
      </div>

      {/* Visual DAG Flow (Horizontal on desktop, vertical on mobile) */}
      <div className="overflow-x-auto pb-2 scrollbar-enterprise">
        <div className="flex flex-col md:flex-row items-center gap-2 min-w-[1020px] py-3 px-1">
          {DAG_NODES.map((node, index) => {
            const status = getStageStatus(node.stageKey);
            const stageData = stages[node.stageKey];
            const isSelected = selectedStageId === node.id;
            const isGate = node.id === "PROMOTION_GATE";
            const Icon = node.icon;

            return (
              <div key={node.id} className="flex items-center gap-2 flex-1">
                {/* Node Card */}
                <motion.div
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  onClick={() => onSelectStage(node.id)}
                  className={cn(
                    "flex flex-col justify-between w-full min-h-[142px] rounded-lg border p-3 cursor-pointer transition-all duration-150 relative",
                    isSelected
                      ? "ring-2 ring-primary border-primary bg-primary/5 shadow-md"
                      : "border-border/80 bg-background/90 hover:border-border hover:bg-muted/30 shadow-xs",
                    status === "RUNNING" && "border-blue-500/60 shadow-[0_0_15px_rgba(59,130,246,0.15)] ring-1 ring-blue-500/50",
                    isGate && "border-purple-500/50 bg-gradient-to-b from-purple-500/5 to-transparent"
                  )}
                >
                  {/* Header */}
                  <div className="flex items-start justify-between gap-1.5">
                    <div className="flex items-center gap-2 min-w-0">
                      <div
                        className={cn(
                          "flex h-7 w-7 items-center justify-center rounded-md border flex-shrink-0",
                          status === "COMPLETED" && "bg-emerald-500/10 border-emerald-500/30 text-emerald-500",
                          status === "RUNNING" && "bg-blue-500/10 border-blue-500/30 text-blue-500",
                          status === "FAILED" && "bg-rose-500/10 border-rose-500/30 text-rose-500",
                          status === "PENDING" && "bg-muted border-border/70 text-muted-foreground",
                          isGate && "bg-purple-500/10 border-purple-500/40 text-purple-500"
                        )}
                      >
                        <Icon className="h-3.5 w-3.5" />
                      </div>
                      <div className="min-w-0">
                        <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-muted-foreground block truncate">
                          {node.agentLabel}
                        </span>
                        <h3 className="text-xs font-semibold text-foreground truncate" title={node.name}>
                          {node.name}
                        </h3>
                      </div>
                    </div>
                  </div>

                  {/* Body Info */}
                  <div className="my-2 space-y-1">
                    <div className="flex items-center justify-between text-[11px] font-mono">
                      <span className="text-muted-foreground/70">Target:</span>
                      <span className="font-medium text-foreground truncate max-w-[100px]" title={node.outputLayer}>
                        {node.outputLayer}
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-[11px] font-mono">
                      <span className="text-muted-foreground/70">Processed:</span>
                      <span className="font-bold text-foreground tabular-nums">
                        {stageData ? `${stageData.records_out.toLocaleString()}` : "0"}
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-[10px] font-mono text-muted-foreground/60">
                      <span>Duration:</span>
                      <span>
                        {stageData?.duration_seconds ? `${stageData.duration_seconds.toFixed(1)}s` : "--"}
                      </span>
                    </div>
                  </div>

                  {/* Status Footer */}
                  <div className="pt-1.5 border-t border-border/50 flex items-center justify-between">
                    {getStatusBadge(status)}
                    {isGate && (
                      <span className="text-[9px] font-mono font-semibold text-purple-600 dark:text-purple-400">
                        GATE ≥ 80
                      </span>
                    )}
                  </div>
                </motion.div>

                {/* Arrow Connector (between nodes) */}
                {index < DAG_NODES.length - 1 && (
                  <div className="hidden md:flex items-center justify-center flex-shrink-0 text-muted-foreground/40">
                    <ArrowRight
                      className={cn(
                        "h-4 w-4 transition-colors",
                        status === "COMPLETED" && "text-emerald-500",
                        status === "RUNNING" && "text-blue-500 animate-pulse"
                      )}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

