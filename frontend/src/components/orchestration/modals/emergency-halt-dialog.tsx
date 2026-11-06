"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { AlertOctagon, ShieldAlert } from "lucide-react";

interface EmergencyHaltDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => Promise<void>;
  isSubmitting: boolean;
  workflowId?: string;
}

export function EmergencyHaltDialog({
  open,
  onOpenChange,
  onConfirm,
  isSubmitting,
  workflowId,
}: EmergencyHaltDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md border-destructive/50 bg-background/95 backdrop-blur-md shadow-2xl p-6">
        <DialogHeader className="space-y-2">
          <div className="flex items-center gap-2.5 text-destructive">
            <div className="flex h-9 w-9 items-center justify-center rounded-md bg-destructive/10 border border-destructive/30">
              <AlertOctagon className="h-5 w-5" />
            </div>
            <DialogTitle className="text-base font-semibold text-destructive">
              Emergency Workflow Halt
            </DialogTitle>
          </div>
          <DialogDescription className="text-xs text-muted-foreground leading-relaxed">
            This will immediately emit an <strong className="text-destructive font-mono">emergency_halt</strong> signal
            to Temporal. Active worker activity executions will be cancelled, uncommitted working-layer batches will roll back safely, and queue ingestion will be paused.
          </DialogDescription>
        </DialogHeader>

        {workflowId && (
          <div className="rounded-md border border-border/80 bg-muted/40 p-2.5 font-mono text-[11px] text-foreground">
            Target Workflow: <span className="text-destructive font-bold">{workflowId}</span>
          </div>
        )}

        <DialogFooter className="gap-2 sm:gap-0 pt-2 border-t border-border/50">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isSubmitting}
            className="text-xs font-mono h-9"
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={onConfirm}
            disabled={isSubmitting}
            className="gap-1.5 text-xs font-semibold h-9 font-mono"
          >
            <ShieldAlert className="h-4 w-4" />
            {isSubmitting ? "Halting Cluster..." : "Confirm Emergency Halt"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

