"use client";

import { PromotionGateTelemetry } from "../types";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Award,
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  ArrowDown,
  Filter,
  ShieldAlert,
  Database,
} from "lucide-react";

interface PromotionGateFunnelProps {
  telemetry?: PromotionGateTelemetry;
}

const DEFAULT_PROMOTION_TELEMETRY: PromotionGateTelemetry = {
  total_candidates: 224500,
  quality_passed: 218900,
  trust_passed: 212400,
  sanctions_cleared: 210838,
  promoted_to_master: 210838,
  quarantined_count: 13662,
  conversion_rate_pct: 93.9,
  rejection_breakdown: {
    low_quality: 5600,
    low_trust: 6500,
    sanction_match: 120,
    schema_violation: 1442,
  },
};

export function PromotionGateFunnel({
  telemetry = DEFAULT_PROMOTION_TELEMETRY,
}: PromotionGateFunnelProps) {
  const steps = [
    {
      title: "Candidate Working Records",
      count: telemetry.total_candidates,
      pct: 100,
      description: "Harvested & clustered entities in working layer",
      color: "bg-blue-500",
    },
    {
      title: "Quality Score Threshold (Quality ≥ 80)",
      count: telemetry.quality_passed,
      pct: (telemetry.quality_passed / (telemetry.total_candidates || 1)) * 100,
      description: "Completeness, syntax validity, and domain resolution",
      color: "bg-cyan-500",
    },
    {
      title: "Bayesian Trust Score (Trust ≥ 0.85)",
      count: telemetry.trust_passed,
      pct: (telemetry.trust_passed / (telemetry.total_candidates || 1)) * 100,
      description: "Corroborated evidence, temporal signals & confidence",
      color: "bg-purple-500",
    },
    {
      title: "Sanctions & Compliance Check",
      count: telemetry.sanctions_cleared,
      pct: (telemetry.sanctions_cleared / (telemetry.total_candidates || 1)) * 100,
      description: "OFAC, PEP, and global regulatory screening",
      color: "bg-indigo-500",
    },
    {
      title: "Promoted to Master Vault (Single Source of Truth)",
      count: telemetry.promoted_to_master,
      pct: (telemetry.promoted_to_master / (telemetry.total_candidates || 1)) * 100,
      description: "Certified Golden Records committed atomically",
      color: "bg-emerald-500",
    },
  ];

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border/70 bg-card p-4 sm:p-5 shadow-xs">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-border/60 pb-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-purple-500/10 text-purple-500">
            <Award className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold tracking-tight text-foreground">
              Mandatory Promotion Gate Certification Funnel
            </h3>
            <p className="text-[11px] font-mono text-muted-foreground">
              Atomic validation filtering pre-master working entities into Certified Golden Master
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Badge
            variant="outline"
            className="font-mono text-xs text-emerald-600 dark:text-emerald-400 border-emerald-500/30 bg-emerald-500/10"
          >
            {telemetry.conversion_rate_pct.toFixed(1)}% VAULT PASS RATE
          </Badge>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 pt-1">
        {/* Visual Step-Down Conversion Funnel (2 cols) */}
        <div className="lg:col-span-2 space-y-3">
          {steps.map((step, idx) => (
            <div key={step.title} className="space-y-1.5">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-foreground flex items-center gap-2">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-muted font-mono text-[10px] text-muted-foreground">
                    {idx + 1}
                  </span>
                  {step.title}
                </span>
                <div className="flex items-center gap-3 font-mono text-xs">
                  <span className="font-bold text-foreground tabular-nums">
                    {step.count.toLocaleString()}
                  </span>
                  <span className="text-muted-foreground tabular-nums w-12 text-right">
                    {step.pct.toFixed(1)}%
                  </span>
                </div>
              </div>

              <Progress value={step.pct} className="h-2 bg-muted/60" />

              <p className="text-[10px] font-mono text-muted-foreground/70 pl-7">
                {step.description}
              </p>
            </div>
          ))}
        </div>

        {/* Rejection & Quarantine Breakdown Card (1 col) */}
        <div className="flex flex-col justify-between rounded-lg border border-border/70 bg-background/80 p-4 space-y-4">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                <ShieldAlert className="h-4 w-4 text-rose-500" /> Quarantined Records
              </span>
              <span className="font-mono text-xs font-bold text-rose-500 tabular-nums">
                {telemetry.quarantined_count.toLocaleString()}
              </span>
            </div>
            <p className="text-[10px] font-mono text-muted-foreground mt-0.5">
              Isolated in DLQ staging — prevented from polluting Master Vault
            </p>
          </div>

          <div className="space-y-2 font-mono text-[11px]">
            <div className="flex items-center justify-between p-2 rounded bg-muted/30 border border-border/50">
              <span className="text-muted-foreground">Quality &lt; 80 Failures:</span>
              <span className="font-bold text-foreground">
                {telemetry.rejection_breakdown.low_quality.toLocaleString()}
              </span>
            </div>

            <div className="flex items-center justify-between p-2 rounded bg-muted/30 border border-border/50">
              <span className="text-muted-foreground">Trust &lt; 0.85 Bayesian:</span>
              <span className="font-bold text-foreground">
                {telemetry.rejection_breakdown.low_trust.toLocaleString()}
              </span>
            </div>

            <div className="flex items-center justify-between p-2 rounded bg-muted/30 border border-border/50">
              <span className="text-muted-foreground">Sanction / PEP Watchlist:</span>
              <span className="font-bold text-rose-500">
                {telemetry.rejection_breakdown.sanction_match.toLocaleString()}
              </span>
            </div>

            <div className="flex items-center justify-between p-2 rounded bg-muted/30 border border-border/50">
              <span className="text-muted-foreground">Schema Incomplete:</span>
              <span className="font-bold text-amber-500">
                {telemetry.rejection_breakdown.schema_violation.toLocaleString()}
              </span>
            </div>
          </div>

          <div className="rounded-md border border-emerald-500/20 bg-emerald-500/5 p-2.5 text-[11px] font-mono text-emerald-600 dark:text-emerald-400 flex items-center gap-2">
            <Database className="h-4 w-4 flex-shrink-0" />
            <span>Master Vault: Zero dirty uncertified writes guarantee</span>
          </div>
        </div>
      </div>
    </div>
  );
}

