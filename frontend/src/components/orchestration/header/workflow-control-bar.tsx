"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Play,
  Pause,
  RotateCw,
  RefreshCcw,
  Square,
  AlertOctagon,
  Sparkles,
} from "lucide-react";
import { EmergencyHaltDialog } from "../modals/emergency-halt-dialog";
import { cn } from "@/lib/utils";

interface WorkflowControlBarProps {
  workflowId: string | null;
  workflowStatus: "IDLE" | "RUNNING" | "COMPLETED" | "FAILED" | "PAUSED" | "TERMINATED";
  onStartClick: () => void;
  onSignal: (signal: string) => Promise<void>;
  isSignaling: boolean;
}

export function WorkflowControlBar({
  workflowId,
  workflowStatus,
  onStartClick,
  onSignal,
  isSignaling,
}: WorkflowControlBarProps) {
  const [haltDialogOpen, setHaltDialogOpen] = useState(false);

  const isRunning = workflowStatus === "RUNNING";
  const isPaused = workflowStatus === "PAUSED";
  const isFailed = workflowStatus === "FAILED";
  const hasActiveWorkflow = Boolean(workflowId && (isRunning || isPaused || isFailed));

  const handleHaltConfirm = async () => {
    await onSignal("emergency_halt");
    setHaltDialogOpen(false);
  };

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 bg-muted/20 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2">
          <span className="text-[11px] uppercase tracking-wider font-semibold text-muted-foreground/70">
            Workflow Control:
          </span>
          {workflowId ? (
            <span className="inline-flex items-center gap-1.5 rounded bg-background px-2 py-0.5 font-mono text-[11px] text-foreground border border-border/80">
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  isRunning && "bg-emerald-500 animate-pulse",
                  isPaused && "bg-amber-500",
                  isFailed && "bg-rose-500",
                  !isRunning && !isPaused && !isFailed && "bg-muted-foreground/60"
                )}
              />
              <span className="font-semibold">{workflowId}</span>
              <span className="text-[10px] text-muted-foreground font-mono">[{workflowStatus}]</span>
            </span>
          ) : (
            <span className="font-mono text-xs text-muted-foreground">Cluster Standby</span>
          )}
        </div>

        {/* Action Button Strip */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Start Scraping */}
          <Button
            size="sm"
            onClick={onStartClick}
            disabled={isSignaling || isRunning}
            className="h-8 gap-1.5 bg-primary font-medium hover:bg-primary/90 text-primary-foreground text-xs shadow-xs"
          >
            <Sparkles className="h-3.5 w-3.5" />
            <span>Start Scraping</span>
          </Button>

          {/* Pause */}
          <Button
            size="sm"
            variant="outline"
            onClick={() => onSignal("pause")}
            disabled={isSignaling || !isRunning}
            className="h-8 gap-1.5 border-amber-500/40 text-amber-600 dark:text-amber-400 hover:bg-amber-500/10 text-xs"
          >
            <Pause className="h-3.5 w-3.5" />
            <span>Pause</span>
          </Button>

          {/* Resume */}
          <Button
            size="sm"
            variant="outline"
            onClick={() => onSignal("resume")}
            disabled={isSignaling || !isPaused}
            className="h-8 gap-1.5 border-blue-500/40 text-blue-600 dark:text-blue-400 hover:bg-blue-500/10 text-xs"
          >
            <Play className="h-3.5 w-3.5 fill-current" />
            <span>Resume</span>
          </Button>

          {/* Retry Failed Phase */}
          <Button
            size="sm"
            variant="outline"
            onClick={() => onSignal("retry_phase")}
            disabled={isSignaling || !isFailed}
            className="h-8 gap-1.5 border-border text-xs hover:bg-muted"
          >
            <RotateCw className="h-3.5 w-3.5 text-muted-foreground" />
            <span>Retry Failed Phase</span>
          </Button>

          {/* Restart Workflow */}
          <Button
            size="sm"
            variant="outline"
            onClick={() => onSignal("restart_workflow")}
            disabled={isSignaling || !hasActiveWorkflow}
            className="h-8 gap-1.5 border-border text-xs hover:bg-muted"
          >
            <RefreshCcw className="h-3.5 w-3.5 text-muted-foreground" />
            <span>Restart Workflow</span>
          </Button>

          {/* Stop Workflow */}
          <Button
            size="sm"
            variant="outline"
            onClick={() => onSignal("stop_workflow")}
            disabled={isSignaling || !hasActiveWorkflow}
            className="h-8 gap-1.5 border-border text-xs hover:bg-muted text-rose-500 hover:text-rose-600 dark:text-rose-400"
          >
            <Square className="h-3.5 w-3.5 fill-current" />
            <span>Stop Workflow</span>
          </Button>

          <div className="h-4 w-px bg-border/80 mx-1 hidden sm:block" />

          {/* Emergency Halt */}
          <Button
            size="sm"
            variant="destructive"
            onClick={() => setHaltDialogOpen(true)}
            disabled={isSignaling}
            className="h-8 gap-1.5 bg-destructive hover:bg-destructive/90 text-destructive-foreground font-semibold text-xs shadow-xs"
          >
            <AlertOctagon className="h-3.5 w-3.5" />
            <span>Emergency Halt</span>
          </Button>
        </div>
      </div>

      <EmergencyHaltDialog
        open={haltDialogOpen}
        onOpenChange={setHaltDialogOpen}
        onConfirm={handleHaltConfirm}
        isSubmitting={isSignaling}
        workflowId={workflowId ?? undefined}
      />
    </>
  );
}

