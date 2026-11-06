"use client";

import { WorkingLayerTelemetry } from "../types";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import {
  Layers,
  GitMerge,
  Mail,
  Users,
  CheckCircle2,
  AlertTriangle,
  ShieldAlert,
  HelpCircle,
  Briefcase,
} from "lucide-react";

interface WorkingLayerMonitorProps {
  telemetry?: WorkingLayerTelemetry;
}

const DEFAULT_WORKING_LAYER: WorkingLayerTelemetry = {
  working_orgs_count: 210950,
  working_emails_count: 580200,
  working_persons_count: 340100,
  clusters_distribution: {
    single_source: 84200,
    multi_source: 118400,
    conflict_resolved: 8350,
  },
  email_tiers: {
    tier1_deliverable: 512400,
    tier2_catch_all: 48900,
    tier3_disposable: 12500,
    tier4_invalid: 5200,
    tier5_spam_trap: 1200,
  },
  executive_depth: {
    c_level: 92400,
    vp: 114200,
    director: 89500,
    manager: 44000,
  },
};

export function WorkingLayerMonitor({ telemetry = DEFAULT_WORKING_LAYER }: WorkingLayerMonitorProps) {
  const totalEmails = Object.values(telemetry.email_tiers).reduce((a, b) => a + b, 0);
  const totalExecs = Object.values(telemetry.executive_depth).reduce((a, b) => a + b, 0);
  const totalClusters = Object.values(telemetry.clusters_distribution).reduce((a, b) => a + b, 0);

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border/70 bg-card p-4 sm:p-5 shadow-xs">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-border/60 pb-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-cyan-500/10 text-cyan-500">
            <Layers className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold tracking-tight text-foreground">
              Pre-Master Working Layer Intelligence
            </h3>
            <p className="text-[11px] font-mono text-muted-foreground">
              Direct pipeline staging before certified promotion gate
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Badge variant="outline" className="font-mono text-[10px] text-cyan-600 dark:text-cyan-400 border-cyan-500/30 bg-cyan-500/10">
            ISOLATED WORKING STORAGE
          </Badge>
        </div>
      </div>

      {/* 3 Main Working Layer Columns */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* 1. working_organizations & Splink */}
        <div className="flex flex-col justify-between rounded-lg border border-border/60 bg-background/70 p-3.5 space-y-3">
          <div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <GitMerge className="h-4 w-4 text-cyan-500" />
                <span className="text-xs font-semibold text-foreground">working_organizations</span>
              </div>
              <span className="font-mono text-xs font-bold text-foreground tabular-nums">
                {telemetry.working_orgs_count.toLocaleString()}
              </span>
            </div>
            <p className="text-[10px] font-mono text-muted-foreground mt-0.5">
              Splink 5.0 DuckDB Fellegi-Sunter Identity Clusters
            </p>
          </div>

          <div className="space-y-2 pt-1">
            <div className="space-y-1">
              <div className="flex items-center justify-between text-[11px] font-mono">
                <span className="text-muted-foreground">Multi-Source Merged</span>
                <span className="font-bold text-emerald-500 tabular-nums">
                  {telemetry.clusters_distribution.multi_source.toLocaleString()} (
                  {((telemetry.clusters_distribution.multi_source / (totalClusters || 1)) * 100).toFixed(1)}%)
                </span>
              </div>
              <Progress
                value={(telemetry.clusters_distribution.multi_source / (totalClusters || 1)) * 100}
                className="h-1.5 bg-muted/60"
              />
            </div>

            <div className="space-y-1">
              <div className="flex items-center justify-between text-[11px] font-mono">
                <span className="text-muted-foreground">Single Source Ingestion</span>
                <span className="font-bold text-foreground tabular-nums">
                  {telemetry.clusters_distribution.single_source.toLocaleString()} (
                  {((telemetry.clusters_distribution.single_source / (totalClusters || 1)) * 100).toFixed(1)}%)
                </span>
              </div>
              <Progress
                value={(telemetry.clusters_distribution.single_source / (totalClusters || 1)) * 100}
                className="h-1.5 bg-muted/60"
              />
            </div>

            <div className="space-y-1">
              <div className="flex items-center justify-between text-[11px] font-mono">
                <span className="text-muted-foreground">Conflict Auto-Resolved</span>
                <span className="font-bold text-cyan-500 tabular-nums">
                  {telemetry.clusters_distribution.conflict_resolved.toLocaleString()} (
                  {((telemetry.clusters_distribution.conflict_resolved / (totalClusters || 1)) * 100).toFixed(1)}%)
                </span>
              </div>
              <Progress
                value={(telemetry.clusters_distribution.conflict_resolved / (totalClusters || 1)) * 100}
                className="h-1.5 bg-muted/60"
              />
            </div>
          </div>
        </div>

        {/* 2. working_emails & 5-Tier RFC 5322 */}
        <div className="flex flex-col justify-between rounded-lg border border-border/60 bg-background/70 p-3.5 space-y-3">
          <div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Mail className="h-4 w-4 text-emerald-500" />
                <span className="text-xs font-semibold text-foreground">working_emails</span>
              </div>
              <span className="font-mono text-xs font-bold text-foreground tabular-nums">
                {telemetry.working_emails_count.toLocaleString()}
              </span>
            </div>
            <p className="text-[10px] font-mono text-muted-foreground mt-0.5">
              5-Tier Verification (RFC 5322 + MX DNS + SMTP Handshake)
            </p>
          </div>

          <div className="space-y-1.5 pt-1 text-[11px] font-mono">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <CheckCircle2 className="h-3 w-3 text-emerald-500" /> Tier 1: Deliverable
              </span>
              <span className="font-bold text-emerald-500 tabular-nums">
                {telemetry.email_tiers.tier1_deliverable.toLocaleString()} (
                {((telemetry.email_tiers.tier1_deliverable / (totalEmails || 1)) * 100).toFixed(1)}%)
              </span>
            </div>

            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <HelpCircle className="h-3 w-3 text-amber-500" /> Tier 2: Catch-All
              </span>
              <span className="font-bold text-amber-500 tabular-nums">
                {telemetry.email_tiers.tier2_catch_all.toLocaleString()}
              </span>
            </div>

            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <AlertTriangle className="h-3 w-3 text-muted-foreground/60" /> Tier 3: Disposable
              </span>
              <span className="font-bold text-muted-foreground tabular-nums">
                {telemetry.email_tiers.tier3_disposable.toLocaleString()}
              </span>
            </div>

            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <ShieldAlert className="h-3 w-3 text-rose-500" /> Tier 4/5: Invalid/Trap
              </span>
              <span className="font-bold text-rose-500 tabular-nums">
                {(telemetry.email_tiers.tier4_invalid + telemetry.email_tiers.tier5_spam_trap).toLocaleString()}
              </span>
            </div>
          </div>
        </div>

        {/* 3. working_persons & Executive Hierarchies */}
        <div className="flex flex-col justify-between rounded-lg border border-border/60 bg-background/70 p-3.5 space-y-3">
          <div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Users className="h-4 w-4 text-purple-500" />
                <span className="text-xs font-semibold text-foreground">working_persons</span>
              </div>
              <span className="font-mono text-xs font-bold text-foreground tabular-nums">
                {telemetry.working_persons_count.toLocaleString()}
              </span>
            </div>
            <p className="text-[10px] font-mono text-muted-foreground mt-0.5">
              Decision Makers & Multi-Level Corporate Career Graph
            </p>
          </div>

          <div className="space-y-1.5 pt-1 text-[11px] font-mono">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <Briefcase className="h-3 w-3 text-purple-500" /> C-Suite (CEO, CTO, CFO)
              </span>
              <span className="font-bold text-purple-500 tabular-nums">
                {telemetry.executive_depth.c_level.toLocaleString()} (
                {((telemetry.executive_depth.c_level / (totalExecs || 1)) * 100).toFixed(1)}%)
              </span>
            </div>

            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <Briefcase className="h-3 w-3 text-blue-500" /> Vice Presidents
              </span>
              <span className="font-bold text-blue-500 tabular-nums">
                {telemetry.executive_depth.vp.toLocaleString()}
              </span>
            </div>

            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <Briefcase className="h-3 w-3 text-foreground/80" /> Directors & Heads
              </span>
              <span className="font-bold text-foreground tabular-nums">
                {telemetry.executive_depth.director.toLocaleString()}
              </span>
            </div>

            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <Briefcase className="h-3 w-3 text-muted-foreground" /> Managers & Leads
              </span>
              <span className="font-bold text-muted-foreground tabular-nums">
                {telemetry.executive_depth.manager.toLocaleString()}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

