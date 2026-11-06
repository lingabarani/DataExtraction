"use client";

import { FreshnessSLATelemetry } from "../types";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import {
  Clock,
  RotateCw,
  Globe2,
  Mail,
  Users,
  Building,
  CheckCircle2,
  AlertTriangle,
  Calendar,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface FreshnessSLADashboardProps {
  telemetry?: FreshnessSLATelemetry;
  onTriggerRevalidation?: () => void;
  isTriggering?: boolean;
}

const DEFAULT_FRESHNESS: FreshnessSLATelemetry = {
  website_30d: {
    sla_window: "Website & Domain (30 Days)",
    target_hours: 720,
    total_records: 210838,
    compliant_records: 198200,
    stale_records: 12638,
    compliance_pct: 94.0,
  },
  email_90d: {
    sla_window: "Email Deliverability (90 Days)",
    target_hours: 2160,
    total_records: 580200,
    compliant_records: 562400,
    stale_records: 17800,
    compliance_pct: 96.9,
  },
  executive_90d: {
    sla_window: "Executive Employment (90 Days)",
    target_hours: 2160,
    total_records: 341200,
    compliant_records: 324100,
    stale_records: 17100,
    compliance_pct: 95.0,
  },
  domain_gov_48d: {
    sla_window: "Government & Reg Registry (48 Days)",
    target_hours: 1152,
    total_records: 200147,
    compliant_records: 195400,
    stale_records: 4747,
    compliance_pct: 97.6,
  },
  overall_sla_score: 95.8,
  revalidation_scheduler_active: true,
  next_scheduled_run: "2026-11-06T00:00:00Z",
};

export function FreshnessSLADashboard({
  telemetry = DEFAULT_FRESHNESS,
  onTriggerRevalidation,
  isTriggering = false,
}: FreshnessSLADashboardProps) {
  const slots = [
    { ...telemetry.website_30d, icon: Globe2, color: "text-blue-500" },
    { ...telemetry.email_90d, icon: Mail, color: "text-emerald-500" },
    { ...telemetry.executive_90d, icon: Users, color: "text-purple-500" },
    { ...telemetry.domain_gov_48d, icon: Building, color: "text-amber-500" },
  ];

  return (
    <div className="flex flex-col gap-4 rounded-xl border border-border/70 bg-card p-4 sm:p-5 shadow-xs">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border/60 pb-3">
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-amber-500/10 text-amber-500">
            <Clock className="h-4 w-4" />
          </div>
          <div>
            <h3 className="text-sm font-semibold tracking-tight text-foreground">
              Autonomous Freshness & SLA Revalidation Engine
            </h3>
            <p className="text-[11px] font-mono text-muted-foreground">
              Lifecycle decay monitoring: 30d Website | 90d Email | 90d Executive | 48d Registry
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          <Badge
            variant="outline"
            className="font-mono text-xs border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
          >
            {telemetry.overall_sla_score.toFixed(1)}% OVERALL COMPLIANCE
          </Badge>

          {onTriggerRevalidation && (
            <Button
              size="sm"
              variant="outline"
              onClick={onTriggerRevalidation}
              disabled={isTriggering}
              className="h-8 gap-1.5 border-border text-xs font-mono"
            >
              <RotateCw className={cn("h-3.5 w-3.5", isTriggering && "animate-spin text-primary")} />
              <span>Trigger Scan</span>
            </Button>
          )}
        </div>
      </div>

      {/* 4 SLA Window Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3 pt-1">
        {slots.map((slot) => {
          const Icon = slot.icon;
          const isHighCompliance = slot.compliance_pct >= 95;

          return (
            <div
              key={slot.sla_window}
              className="flex flex-col justify-between rounded-lg border border-border/60 bg-background/80 p-3.5 space-y-3"
            >
              <div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Icon className={cn("h-4 w-4", slot.color)} />
                    <span className="text-xs font-semibold text-foreground truncate max-w-[150px]">
                      {slot.sla_window}
                    </span>
                  </div>
                  <Badge
                    variant="outline"
                    className={cn(
                      "font-mono text-[9px] py-0",
                      isHighCompliance
                        ? "border-emerald-500/30 text-emerald-500 bg-emerald-500/5"
                        : "border-amber-500/30 text-amber-500 bg-amber-500/5"
                    )}
                  >
                    {slot.compliance_pct.toFixed(1)}%
                  </Badge>
                </div>

                <div className="mt-3 space-y-1">
                  <Progress value={slot.compliance_pct} className="h-1.5 bg-muted/60" />
                </div>
              </div>

              {/* Stats */}
              <div className="grid grid-cols-2 gap-2 text-[11px] font-mono border-t border-border/50 pt-2">
                <div>
                  <span className="text-[10px] text-muted-foreground uppercase block">Compliant</span>
                  <span className="font-bold text-foreground tabular-nums">
                    {slot.compliant_records.toLocaleString()}
                  </span>
                </div>
                <div>
                  <span className="text-[10px] text-muted-foreground uppercase block">Stale / Due</span>
                  <span
                    className={cn(
                      "font-bold tabular-nums",
                      slot.stale_records > 0 ? "text-amber-500" : "text-muted-foreground"
                    )}
                  >
                    {slot.stale_records.toLocaleString()}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Next Scheduled Revalidation Run */}
      <div className="flex flex-wrap items-center justify-between rounded-lg border border-border/60 bg-muted/20 px-3.5 py-2.5 text-xs font-mono text-muted-foreground">
        <div className="flex items-center gap-2">
          <Calendar className="h-4 w-4 text-primary" />
          <span>Next Scheduled Revalidation Wave:</span>
          <span className="font-semibold text-foreground">
            {new Date(telemetry.next_scheduled_run).toLocaleString()}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-foreground">Temporal Revalidation Cron Daemon ACTIVE</span>
        </div>
      </div>
    </div>
  );
}

