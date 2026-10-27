"use client";

import React, { useState } from "react";
import {
  Calendar, Clock, Play, Pause, RefreshCw, CheckCircle2,
  Workflow, ArrowRight, ShieldCheck
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

interface ScheduleItem {
  id: string;
  workflow: string;
  cron: string;
  description: string;
  queue: string;
  nextRun: string;
  lastRun: string;
  status: "ACTIVE" | "PAUSED";
}

const SCHEDULES: ScheduleItem[] = [
  {
    id: "daily-federal-ingestion",
    workflow: "FederalIngestionWorkflow",
    cron: "0 2 * * *",
    description: "Daily incremental ingestion of 6 federal registries (CMS, SEC, FDIC, USAspending, ProPublica, SAM.gov)",
    queue: "federal-ingestion",
    nextRun: "Tonight at 02:00 UTC",
    lastRun: "Today at 02:00 UTC (Success)",
    status: "ACTIVE",
  },
  {
    id: "weekly-gmaps-extraction",
    workflow: "GMapsExtractionWorkflow",
    cron: "0 1 * * 0",
    description: "Weekly Google Maps B2B regional collection across high-density metro coordinates with website verification",
    queue: "gmaps-extraction",
    nextRun: "Sunday at 01:00 UTC",
    lastRun: "3 days ago (Success)",
    status: "ACTIVE",
  },
  {
    id: "monthly-osm-extraction",
    workflow: "OSMStateWorkflow",
    cron: "0 3 1 * *",
    description: "Monthly full Overpass quadtree spatial extraction across 50 US states & 13 POI categories",
    queue: "osm-extraction",
    nextRun: "Nov 1 at 03:00 UTC",
    lastRun: "25 days ago (Success)",
    status: "ACTIVE",
  },
  {
    id: "hourly-dlq-sweep",
    workflow: "DLQReplayWorkflow",
    cron: "0 * * * *",
    description: "Autonomous Dead-Letter Queue sweep and quarantine replay for transient failures",
    queue: "storage-ops",
    nextRun: "In 34 minutes",
    lastRun: "26 mins ago (Success)",
    status: "ACTIVE",
  },
];

export function SchedulesPanel() {
  const [schedules, setSchedules] = useState<ScheduleItem[]>(SCHEDULES);

  const toggleStatus = (id: string) => {
    setSchedules((prev) =>
      prev.map((s) => {
        if (s.id === id) {
          return {
            ...s,
            status: s.status === "ACTIVE" ? "PAUSED" : "ACTIVE",
          };
        }
        return s;
      })
    );
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">Temporal Automated Schedules</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Deterministic cron triggers managed natively by the Temporal schedule engine with zero cron drift.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="px-3 py-1 bg-emerald-500/10 text-emerald-600 border-emerald-500/20 text-xs font-medium">
            <ShieldCheck className="w-3.5 h-3.5 mr-1.5" />
            Temporal Server Schedules Active
          </Badge>
        </div>
      </div>

      {/* Schedules List */}
      <div className="grid grid-cols-1 gap-4">
        {schedules.map((sched) => (
          <Card key={sched.id} className="relative">
            <CardHeader className="p-5 pb-3">
              <div className="flex flex-col md:flex-row md:items-start justify-between gap-3">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Calendar className="w-4 h-4 text-primary" />
                    <CardTitle className="text-base font-semibold">{sched.id}</CardTitle>
                    <Badge
                      variant="outline"
                      className={`text-[11px] font-medium border ${
                        sched.status === "ACTIVE"
                          ? "bg-emerald-500/10 text-emerald-600 border-emerald-500/20"
                          : "bg-muted text-muted-foreground border-border"
                      }`}
                    >
                      {sched.status}
                    </Badge>
                  </div>
                  <CardDescription className="text-xs max-w-2xl">
                    {sched.description}
                  </CardDescription>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => toggleStatus(sched.id)}
                    className="h-8 text-xs"
                  >
                    {sched.status === "ACTIVE" ? (
                      <>
                        <Pause className="w-3 h-3 mr-1" />
                        Pause Schedule
                      </>
                    ) : (
                      <>
                        <Play className="w-3 h-3 mr-1" />
                        Resume Schedule
                      </>
                    )}
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="p-5 pt-0">
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4 p-3 rounded-lg bg-muted/40 border border-border/50 text-xs mt-2">
                <div>
                  <span className="text-muted-foreground font-medium block mb-0.5">Cron Spec:</span>
                  <code className="font-mono bg-background px-2 py-0.5 rounded border border-border text-[11px]">
                    {sched.cron}
                  </code>
                </div>
                <div>
                  <span className="text-muted-foreground font-medium block mb-0.5">Target Workflow:</span>
                  <span className="font-mono font-medium text-foreground text-[11px]">
                    {sched.workflow}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground font-medium block mb-0.5">Task Queue:</span>
                  <span className="font-mono text-muted-foreground text-[11px]">
                    {sched.queue}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground font-medium block mb-0.5">Next Execution:</span>
                  <span className="font-medium text-foreground flex items-center gap-1">
                    <Clock className="w-3 h-3 text-primary" />
                    {sched.nextRun}
                  </span>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

