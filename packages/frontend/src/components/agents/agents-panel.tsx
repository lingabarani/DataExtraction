"use client";

import React, { useState } from "react";
import {
  Bot, ShieldAlert, CheckCircle, XCircle, ArrowUpRight,
  Clock, Cpu, Database, RefreshCw, AlertTriangle
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

interface AgentStatus {
  name: string;
  role: string;
  status: "NOMINAL" | "THROTTLING" | "EVALUATING" | "ACTION_REQUIRED";
  lastCycle: string;
  cycleInterval: string;
  confidence: number;
  lastDecision: string;
}

interface ApprovalItem {
  id: string;
  agent: string;
  action: string;
  rationale: string;
  severity: "HIGH" | "CRITICAL";
  timestamp: string;
  confidence: number;
}

const AGENTS: AgentStatus[] = [
  {
    name: "DataQualityAgent",
    role: "Dead-Letter Queue Backpressure & Anomaly Replay",
    status: "NOMINAL",
    lastCycle: "1 min ago",
    cycleInterval: "5m",
    confidence: 0.98,
    lastDecision: "DLQ backlog is 0 — no replay required",
  },
  {
    name: "PipelineCoordinatorAgent",
    role: "Extraction to Enrichment Automated Chaining",
    status: "NOMINAL",
    lastCycle: "3 mins ago",
    cycleInterval: "5m",
    confidence: 0.95,
    lastDecision: "All completed runs chained to LeadEnrichmentWorkflow",
  },
  {
    name: "ResourceManagerAgent",
    role: "DB Connection Pool & External API Rate Limits",
    status: "NOMINAL",
    lastCycle: "2 mins ago",
    cycleInterval: "5m",
    confidence: 1.0,
    lastDecision: "DB pool utilization 38% — nominal conditions",
  },
  {
    name: "FederalExtractionAgent",
    role: "Federal Data Freshness & Quota Allocation",
    status: "NOMINAL",
    lastCycle: "4 mins ago",
    cycleInterval: "15m",
    confidence: 0.92,
    lastDecision: "All 6 federal sources within 7-day freshness SLA",
  },
];

const INITIAL_APPROVALS: ApprovalItem[] = [
  {
    id: "appr-dlq-502",
    agent: "DataQualityAgent",
    action: "Replay 450 Quarantined Records",
    rationale: "DLQ backlog (450 records) exceeds auto-replay threshold of 100. Manual operator confirmation required before storage batch commit.",
    severity: "HIGH",
    timestamp: "12 mins ago",
    confidence: 0.94,
  },
];

export function AgentsPanel() {
  const [approvals, setApprovals] = useState<ApprovalItem[]>(INITIAL_APPROVALS);

  const handleApprove = (id: string) => {
    setApprovals((prev) => prev.filter((a) => a.id !== id));
  };

  const handleReject = (id: string) => {
    setApprovals((prev) => prev.filter((a) => a.id !== id));
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Autonomous Agent Supervision</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            4 AI supervisor agents monitoring quality, resource limits, source freshness, and pipeline coordination.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="px-3 py-1 bg-emerald-500/10 text-emerald-600 border-emerald-500/20 text-xs font-medium">
            <span className="w-2 h-2 rounded-full bg-emerald-500 mr-2 animate-pulse" />
            4 Agents Active (Temporal-Native)
          </Badge>
        </div>
      </div>

      {/* Human Approval Queue */}
      {approvals.length > 0 && (
        <Card className="border-amber-500/30 bg-amber-500/5 dark:bg-amber-500/10">
          <CardHeader className="p-4 pb-2 border-b border-amber-500/20">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-500" />
                <CardTitle className="text-sm font-semibold text-amber-900 dark:text-amber-200">
                  Human Approval Decision Gate ({approvals.length} Pending)
                </CardTitle>
              </div>
              <span className="text-[11px] text-amber-700 dark:text-amber-300 font-medium">
                Mandatory Safety Gate
              </span>
            </div>
          </CardHeader>
          <CardContent className="p-0 divide-y divide-amber-500/20">
            {approvals.map((appr) => (
              <div key={appr.id} className="p-4 flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-xs text-foreground">{appr.action}</span>
                    <Badge variant="outline" className="text-[10px] bg-amber-500/10 text-amber-600 border-amber-500/30">
                      {appr.agent}
                    </Badge>
                    <span className="text-xs text-muted-foreground">{appr.timestamp}</span>
                  </div>
                  <p className="text-xs text-muted-foreground max-w-2xl leading-relaxed">
                    {appr.rationale}
                  </p>
                </div>
                <div className="flex items-center gap-2 self-end md:self-center">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleReject(appr.id)}
                    className="h-8 text-xs text-muted-foreground hover:text-red-500"
                  >
                    <XCircle className="w-3.5 h-3.5 mr-1" />
                    Reject
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => handleApprove(appr.id)}
                    className="h-8 text-xs bg-amber-600 hover:bg-amber-700 text-white font-medium"
                  >
                    <CheckCircle className="w-3.5 h-3.5 mr-1" />
                    Approve Action
                  </Button>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Agents Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {AGENTS.map((agent) => (
          <Card key={agent.name} className="relative overflow-hidden">
            <CardHeader className="p-5 pb-3">
              <div className="flex items-start justify-between">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Bot className="w-4 h-4 text-primary" />
                    <CardTitle className="text-base font-semibold">{agent.name}</CardTitle>
                  </div>
                  <CardDescription className="text-xs">{agent.role}</CardDescription>
                </div>
                <Badge
                  variant="outline"
                  className="text-[11px] font-medium bg-emerald-500/10 text-emerald-600 border-emerald-500/20"
                >
                  {agent.status}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="p-5 pt-0 space-y-4">
              <div className="p-3 rounded-lg bg-muted/40 border border-border/50 text-xs">
                <span className="text-muted-foreground font-medium block mb-1">Latest Observation Rationale:</span>
                <span className="text-foreground font-medium">{agent.lastDecision}</span>
              </div>

              <div className="flex items-center justify-between text-xs text-muted-foreground pt-1 border-t border-border/50">
                <div className="flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5" />
                  <span>Cycle: every {agent.cycleInterval}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <Cpu className="w-3.5 h-3.5" />
                  <span>Confidence: {(agent.confidence * 100).toFixed(0)}%</span>
                </div>
                <span>Last active: {agent.lastCycle}</span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

