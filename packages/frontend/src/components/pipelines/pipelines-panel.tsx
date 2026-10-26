"use client";

import React, { useState, useEffect } from "react";
import {
  Play, Pause, RefreshCw, XCircle, CheckCircle2,
  Clock, Server, Activity, ShieldCheck, ChevronRight
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

interface WorkflowItem {
  id: string;
  type: string;
  queue: string;
  status: "RUNNING" | "COMPLETED" | "PAUSED" | "FAILED";
  phase: string;
  startTime: string;
  duration: string;
  progress: number;
}

const INITIAL_WORKFLOWS: WorkflowItem[] = [
  {
    id: "master-daily-9a1b4e",
    type: "MasterOrchestrationWorkflow",
    queue: "federal-ingestion",
    status: "RUNNING",
    phase: "FEDERAL_INGESTION (CMS NPI)",
    startTime: "10 mins ago",
    duration: "10m 24s",
    progress: 45,
  },
  {
    id: "gmaps-batch-7f83a2",
    type: "GMapsExtractionWorkflow",
    queue: "gmaps-extraction",
    status: "RUNNING",
    phase: "WEBSITE_VERIFICATION",
    startTime: "32 mins ago",
    duration: "32m 10s",
    progress: 68,
  },
  {
    id: "osm-state-tx-c8201a",
    type: "OSMStateWorkflow",
    queue: "osm-extraction",
    status: "COMPLETED",
    phase: "CHECKPOINT_RECONCILED",
    startTime: "1 hour ago",
    duration: "14m 18s",
    progress: 100,
  },
  {
    id: "dlq-replay-auto-319b",
    type: "DLQReplayWorkflow",
    queue: "storage-ops",
    status: "COMPLETED",
    phase: "BATCH_COMMITTED",
    startTime: "2 hours ago",
    duration: "1m 42s",
    progress: 100,
  },
];

export function PipelinesPanel() {
  const [workflows, setWorkflows] = useState<WorkflowItem[]>(INITIAL_WORKFLOWS);
  const [filterQueue, setFilterQueue] = useState<string>("all");
  const [isStarting, setIsStarting] = useState(false);
  const [lastRefreshed, setLastRefreshed] = useState<string>(new Date().toLocaleTimeString());

  const handleStartMaster = async () => {
    setIsStarting(true);
    try {
      const newWf: WorkflowItem = {
        id: `master-${Math.random().toString(36).substring(2, 8)}`,
        type: "MasterOrchestrationWorkflow",
        queue: "federal-ingestion",
        status: "RUNNING",
        phase: "INITIALIZING",
        startTime: "Just now",
        duration: "0s",
        progress: 5,
      };
      setWorkflows([newWf, ...workflows]);
    } finally {
      setTimeout(() => setIsStarting(false), 600);
    }
  };

  const handleSignal = (id: string, action: "pause" | "resume" | "cancel") => {
    setWorkflows((prev) =>
      prev.map((w) => {
        if (w.id === id) {
          if (action === "pause") return { ...w, status: "PAUSED" };
          if (action === "resume") return { ...w, status: "RUNNING" };
          if (action === "cancel") return { ...w, status: "FAILED", phase: "CANCELLED_BY_OPERATOR" };
        }
        return w;
      })
    );
  };

  const filtered = filterQueue === "all"
    ? workflows
    : workflows.filter((w) => w.queue === filterQueue);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Temporal Workflow Orchestration</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Distributed execution topology across 5 isolated task queues with saga compensation.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setLastRefreshed(new Date().toLocaleTimeString())}
            className="text-xs h-9"
          >
            <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
            Updated {lastRefreshed}
          </Button>
          <Button
            size="sm"
            onClick={handleStartMaster}
            disabled={isStarting}
            className="h-9 px-4 bg-primary text-primary-foreground font-medium"
          >
            <Play className="w-3.5 h-3.5 mr-1.5 fill-current" />
            {isStarting ? "Triggering..." : "Start Master Pipeline"}
          </Button>
        </div>
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="p-4 pb-2">
            <CardDescription className="text-xs font-medium">Active Workflows</CardDescription>
            <CardTitle className="text-2xl font-bold text-foreground">
              {workflows.filter((w) => w.status === "RUNNING").length}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            <p className="text-xs text-muted-foreground flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              Executing on worker nodes
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="p-4 pb-2">
            <CardDescription className="text-xs font-medium">Queues Online</CardDescription>
            <CardTitle className="text-2xl font-bold text-foreground">5 / 5</CardTitle>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            <p className="text-xs text-muted-foreground flex items-center gap-1.5">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
              All task queues healthy
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="p-4 pb-2">
            <CardDescription className="text-xs font-medium">Completed Today</CardDescription>
            <CardTitle className="text-2xl font-bold text-foreground">48</CardTitle>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            <p className="text-xs text-muted-foreground flex items-center gap-1.5">
              <CheckCircle2 className="w-3.5 h-3.5 text-blue-500" />
              100% saga completion rate
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="p-4 pb-2">
            <CardDescription className="text-xs font-medium">Retry Policy</CardDescription>
            <CardTitle className="text-2xl font-bold text-foreground">Exponential</CardTitle>
          </CardHeader>
          <CardContent className="p-4 pt-0">
            <p className="text-xs text-muted-foreground flex items-center gap-1.5">
              <Activity className="w-3.5 h-3.5 text-purple-500" />
              Backoff coefficient 2.0x
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Filter Tabs */}
      <div className="flex items-center gap-2 border-b border-border pb-2 overflow-x-auto text-xs">
        <span className="text-muted-foreground font-medium mr-1">Filter Queue:</span>
        {["all", "federal-ingestion", "gmaps-extraction", "osm-extraction", "data-pipeline", "storage-ops"].map((q) => (
          <button
            key={q}
            onClick={() => setFilterQueue(q)}
            className={`px-3 py-1.5 rounded-md font-medium transition-colors ${
              filterQueue === q
                ? "bg-secondary text-secondary-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
            }`}
          >
            {q === "all" ? "All Queues" : q}
          </button>
        ))}
      </div>

      {/* Workflows List */}
      <Card>
        <CardHeader className="p-5 border-b border-border">
          <CardTitle className="text-base font-semibold">Active & Recent Workflow Executions</CardTitle>
          <CardDescription className="text-xs">
            Query live execution stack, activity progress, and send runtime signals.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0 divide-y divide-border">
          {filtered.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted-foreground">
              No workflow executions matching selected queue.
            </div>
          ) : (
            filtered.map((wf) => (
              <div key={wf.id} className="p-4 flex flex-col md:flex-row md:items-center justify-between gap-4 hover:bg-muted/30 transition-colors">
                <div className="space-y-1.5 flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-semibold text-foreground">{wf.id}</span>
                    <Badge
                      variant="outline"
                      className={`text-[11px] font-medium border ${
                        wf.status === "RUNNING"
                          ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20"
                          : wf.status === "PAUSED"
                          ? "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20"
                          : wf.status === "FAILED"
                          ? "bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20"
                          : "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20"
                      }`}
                    >
                      {wf.status}
                    </Badge>
                    <span className="text-[11px] text-muted-foreground font-mono bg-muted/60 px-2 py-0.5 rounded">
                      {wf.queue}
                    </span>
                  </div>
                  <div className="text-xs text-foreground font-medium flex items-center gap-1.5">
                    <span>{wf.type}</span>
                    <ChevronRight className="w-3 h-3 text-muted-foreground" />
                    <span className="text-muted-foreground">{wf.phase}</span>
                  </div>
                  {/* Progress bar */}
                  {wf.status === "RUNNING" && (
                    <div className="w-full max-w-md bg-muted rounded-full h-1.5 overflow-hidden">
                      <div
                        className="bg-primary h-1.5 rounded-full transition-all duration-300"
                        style={{ width: `${wf.progress}%` }}
                      />
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-4 text-xs text-muted-foreground">
                  <div className="flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5" />
                    <span>{wf.duration}</span>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-1.5">
                    {wf.status === "RUNNING" && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleSignal(wf.id, "pause")}
                        className="h-8 text-xs"
                      >
                        <Pause className="w-3 h-3 mr-1" />
                        Pause
                      </Button>
                    )}
                    {wf.status === "PAUSED" && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleSignal(wf.id, "resume")}
                        className="h-8 text-xs text-emerald-600"
                      >
                        <Play className="w-3 h-3 mr-1" />
                        Resume
                      </Button>
                    )}
                    {wf.status !== "COMPLETED" && wf.status !== "FAILED" && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleSignal(wf.id, "cancel")}
                        className="h-8 text-xs text-muted-foreground hover:text-red-500"
                      >
                        <XCircle className="w-3.5 h-3.5" />
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  );
}
