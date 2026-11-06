"use client";

import { useState } from "react";
import { OneReachDeliveryTelemetry, OneReachDeliveryItem } from "../types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Send,
  CheckCircle2,
  Clock,
  ExternalLink,
  Code2,
  Radio,
  RotateCw,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface OneReachDeliveryCenterProps {
  telemetry?: OneReachDeliveryTelemetry;
}

const DEFAULT_ONEREACH: OneReachDeliveryTelemetry = {
  total_dispatched: 0,
  delivered_success: 0,
  failed_retry: 0,
  avg_latency_ms: 0,
  success_rate_pct: 100.0,
  endpoint: "https://api.onereach.ai/v2/webhooks/b2b-certified-golden",
  recent_deliveries: [],
};

export function OneReachDeliveryCenter({
  telemetry = DEFAULT_ONEREACH,
}: OneReachDeliveryCenterProps) {
  const [selectedItem, setSelectedItem] = useState<OneReachDeliveryItem | null>(null);

  return (
    <>
      <div className="flex flex-col gap-4 rounded-xl border border-border/70 bg-card p-4 sm:p-5 shadow-xs">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-border/60 pb-3">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-emerald-500/10 text-emerald-500">
              <Send className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold tracking-tight text-foreground">
                OneReach Outbound Delivery Command Center
              </h3>
              <p className="text-[11px] font-mono text-muted-foreground">
                Real-time delivery of certified Golden Records to downstream AI agents and conversational webhooks
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Badge
              variant="outline"
              className="font-mono text-xs text-emerald-600 dark:text-emerald-400 border-emerald-500/30 bg-emerald-500/10"
            >
              {telemetry.success_rate_pct.toFixed(1)}% OUTBOUND SUCCESS
            </Badge>
          </div>
        </div>

        {/* 4 Telemetry Metrics */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 pt-1">
          <div className="rounded-lg border border-border/60 bg-background/80 p-3">
            <span className="text-[10px] uppercase font-semibold text-muted-foreground block">
              Total Dispatched
            </span>
            <span className="font-mono text-lg font-bold text-foreground tabular-nums">
              {telemetry.total_dispatched.toLocaleString()}
            </span>
          </div>

          <div className="rounded-lg border border-border/60 bg-background/80 p-3">
            <span className="text-[10px] uppercase font-semibold text-muted-foreground block">
              Delivered (HTTP 200)
            </span>
            <span className="font-mono text-lg font-bold text-emerald-600 dark:text-emerald-400 tabular-nums">
              {telemetry.delivered_success.toLocaleString()}
            </span>
          </div>

          <div className="rounded-lg border border-border/60 bg-background/80 p-3">
            <span className="text-[10px] uppercase font-semibold text-muted-foreground block">
              Retry / Backoff
            </span>
            <span
              className={cn(
                "font-mono text-lg font-bold tabular-nums",
                telemetry.failed_retry > 0 ? "text-amber-500" : "text-foreground"
              )}
            >
              {telemetry.failed_retry}
            </span>
          </div>

          <div className="rounded-lg border border-border/60 bg-background/80 p-3">
            <span className="text-[10px] uppercase font-semibold text-muted-foreground block">
              Avg Latency
            </span>
            <span className="font-mono text-lg font-bold text-foreground tabular-nums">
              {telemetry.avg_latency_ms}ms
            </span>
          </div>
        </div>

        {/* Recent Deliveries Table */}
        <div className="space-y-2 pt-1">
          <div className="flex items-center justify-between text-xs">
            <span className="font-semibold text-muted-foreground">Recent Webhook Invocations</span>
            <span className="font-mono text-[11px] text-muted-foreground/60 truncate max-w-[300px]">
              Endpoint: {telemetry.endpoint}
            </span>
          </div>

          <div className="overflow-x-auto scrollbar-enterprise rounded-lg border border-border/60">
            <table className="w-full text-left text-xs font-mono">
              <thead>
                <tr className="border-b border-border/60 bg-muted/30 text-[11px] text-muted-foreground/70 uppercase">
                  <th className="py-2 px-3 font-semibold">Entity Name</th>
                  <th className="py-2 px-3 font-semibold">Golden ID</th>
                  <th className="py-2 px-3 font-semibold text-center">Status</th>
                  <th className="py-2 px-3 font-semibold text-right">Latency</th>
                  <th className="py-2 px-3 font-semibold text-right">Timestamp</th>
                  <th className="py-2 px-3 font-semibold text-center">Payload</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50 text-[11px]">
                {telemetry.recent_deliveries.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-8 text-center text-muted-foreground">
                      <div className="flex flex-col items-center justify-center gap-1.5">
                        <Send className="h-5 w-5 text-muted-foreground/30 mb-1" />
                        <span className="font-semibold text-foreground">No Outbound Webhooks Dispatched</span>
                        <span className="text-[11px] text-muted-foreground max-w-sm text-center">
                          OneReach endpoint is in standby mode. Real outbound delivery logs will appear here upon dispatch from Export Manager.
                        </span>
                      </div>
                    </td>
                  </tr>
                ) : (
                  telemetry.recent_deliveries.map((item) => (
                    <tr key={item.id} className="hover:bg-muted/20 transition-colors">
                      <td className="py-2.5 px-3 font-semibold text-foreground">{item.org_name}</td>
                      <td className="py-2.5 px-3 text-muted-foreground">{item.golden_id}</td>
                      <td className="py-2.5 px-3 text-center">
                        <Badge
                          variant="outline"
                          className="font-mono text-[9px] py-0 border-emerald-500/30 bg-emerald-500/10 text-emerald-500"
                        >
                          {item.status}
                        </Badge>
                      </td>
                      <td className="py-2.5 px-3 text-right text-muted-foreground">{item.latency_ms}ms</td>
                      <td className="py-2.5 px-3 text-right text-muted-foreground/70">
                        {new Date(item.timestamp).toLocaleTimeString()}
                      </td>
                      <td className="py-2.5 px-3 text-center">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setSelectedItem(item)}
                          className="h-6 px-2 text-[10px] gap-1 font-mono text-primary hover:bg-primary/10"
                        >
                          <Code2 className="h-3 w-3" />
                          View
                        </Button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Payload Modal */}
      {selectedItem && (
        <Dialog open={Boolean(selectedItem)} onOpenChange={(open) => !open && setSelectedItem(null)}>
          <DialogContent className="max-w-xl border-border bg-background p-6">
            <DialogHeader className="space-y-1">
              <DialogTitle className="text-base font-semibold">
                OneReach Webhook Payload Receipt
              </DialogTitle>
              <DialogDescription className="text-xs text-muted-foreground font-mono">
                {selectedItem.id} — {selectedItem.org_name}
              </DialogDescription>
            </DialogHeader>

            <div className="rounded-lg bg-zinc-950 p-4 border border-zinc-800 text-emerald-400 font-mono text-xs overflow-x-auto max-h-80 scrollbar-enterprise">
              <pre>{JSON.stringify(JSON.parse(selectedItem.payload_summary), null, 2)}</pre>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}

