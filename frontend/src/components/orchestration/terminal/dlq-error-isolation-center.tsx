"use client";

import { useState } from "react";
import { DLQRecord } from "../types";
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
  ShieldAlert,
  RotateCw,
  Trash2,
  Download,
  AlertTriangle,
  Code2,
  CheckSquare,
  Square,
  Search,
} from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

interface DLQErrorIsolationCenterProps {
  records?: DLQRecord[];
  onReplay?: (recordIds: (string | number)[]) => Promise<void>;
  onDiscard?: (recordIds: (string | number)[]) => Promise<void>;
}

const DEFAULT_DLQ_RECORDS: DLQRecord[] = [
  {
    id: "dlq_001",
    source_agent: "Agent 7: Email Discovery",
    entity_type: "email",
    record_identifier: "contact@defunctdomain-xyz.com",
    error_reason: "SMTP handshake failed: 550 Mailbox unavailable or connection dropped",
    error_category: "SMTP_TIMEOUT",
    quarantined_at: "2026-11-05T07:13:08Z",
    retry_count: 3,
    status: "PENDING",
    payload: {
      raw_email: "contact@defunctdomain-xyz.com",
      domain: "defunctdomain-xyz.com",
      mx_record: "mail.defunctdomain-xyz.com",
      tier: 4,
    },
  },
  {
    id: "dlq_002",
    source_agent: "Promotion Gate",
    entity_type: "organization",
    record_identifier: "Pacific Crest Holdings LLC",
    error_reason: "Bayesian quality score below threshold: Quality=74 (minimum required: 80)",
    error_category: "SCHEMA_VALIDATION",
    quarantined_at: "2026-11-05T07:13:14Z",
    retry_count: 0,
    status: "PENDING",
    payload: {
      org_id: "org_work_88192a01",
      name: "Pacific Crest Holdings LLC",
      domain: null,
      jurisdiction: "CA",
      quality_score: 74,
      trust_score: 0.82,
    },
  },
  {
    id: "dlq_003",
    source_agent: "Agent 5: Governance",
    entity_type: "person",
    record_identifier: "Dmitri Volkov",
    error_reason: "OFAC SDN Watchlist match: Potential Sanctions designation flag triggered",
    error_category: "SANCTION_MATCH",
    quarantined_at: "2026-11-05T07:13:13Z",
    retry_count: 0,
    status: "PENDING",
    payload: {
      person_id: "pers_work_119020ff",
      full_name: "Dmitri Volkov",
      role: "Board Member",
      sanction_source: "OFAC_SDN_LIST",
      confidence: 0.98,
    },
  },
  {
    id: "dlq_004",
    source_agent: "Agent 3: Identity Resolution",
    entity_type: "organization",
    record_identifier: "Nexus Innovations Inc",
    error_reason: "Unresolvable duplicate name collision: Splink match probability 0.52 (ambiguous)",
    error_category: "COLLISION",
    quarantined_at: "2026-11-05T07:13:05Z",
    retry_count: 1,
    status: "PENDING",
    payload: {
      org_id: "org_work_550012bc",
      primary_name: "Nexus Innovations Inc",
      conflicting_org_ids: ["org_work_550012bc", "org_work_994110ee"],
      match_probability: 0.52,
    },
  },
];

export function DLQErrorIsolationCenter({
  records = DEFAULT_DLQ_RECORDS,
  onReplay,
  onDiscard,
}: DLQErrorIsolationCenterProps) {
  const [selectedIds, setSelectedIds] = useState<(string | number)[]>([]);
  const [inspectRecord, setInspectRecord] = useState<DLQRecord | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);

  const displayRecords = records.length > 0 ? records : DEFAULT_DLQ_RECORDS;

  const toggleSelectAll = () => {
    if (selectedIds.length === displayRecords.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(displayRecords.map((r) => r.id));
    }
  };

  const toggleSelect = (id: string | number) => {
    if (selectedIds.includes(id)) {
      setSelectedIds(selectedIds.filter((item) => item !== id));
    } else {
      setSelectedIds([...selectedIds, id]);
    }
  };

  const handleReplay = async () => {
    if (selectedIds.length === 0) return;
    setIsProcessing(true);
    try {
      if (onReplay) {
        await onReplay(selectedIds);
      } else {
        toast.success(`Replaying ${selectedIds.length} quarantined records back into staging queues.`);
      }
      setSelectedIds([]);
    } catch {
      toast.error("Replay operation failed");
    } finally {
      setIsProcessing(false);
    }
  };

  const handleDiscard = async () => {
    if (selectedIds.length === 0) return;
    setIsProcessing(true);
    try {
      if (onDiscard) {
        await onDiscard(selectedIds);
      } else {
        toast.success(`Discarded ${selectedIds.length} records from DLQ repository.`);
      }
      setSelectedIds([]);
    } catch {
      toast.error("Discard operation failed");
    } finally {
      setIsProcessing(false);
    }
  };

  const handleExportBatch = () => {
    const raw = JSON.stringify(displayRecords, null, 2);
    const blob = new Blob([raw], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `dlq-error-quarantine-batch.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Quarantined records exported as JSON");
  };

  return (
    <>
      <div className="flex flex-col gap-4 rounded-xl border border-destructive/40 bg-card p-4 sm:p-5 shadow-xs">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border/60 pb-3">
          <div className="flex items-center gap-2">
            <div className="flex h-7 w-7 items-center justify-center rounded-md bg-destructive/10 text-destructive">
              <ShieldAlert className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold tracking-tight text-foreground">
                Dead-Letter Queue (DLQ) & Error Isolation Center
              </h3>
              <p className="text-[11px] font-mono text-muted-foreground">
                Quarantined records isolated to ensure 100% data integrity in Master Vault
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={handleReplay}
              disabled={selectedIds.length === 0 || isProcessing}
              className="h-8 gap-1.5 border-border text-xs font-mono"
            >
              <RotateCw className="h-3 w-3 text-emerald-500" />
              <span>Replay Selected ({selectedIds.length})</span>
            </Button>

            <Button
              size="sm"
              variant="outline"
              onClick={handleDiscard}
              disabled={selectedIds.length === 0 || isProcessing}
              className="h-8 gap-1.5 border-border text-xs font-mono text-rose-500 hover:text-rose-600"
            >
              <Trash2 className="h-3 w-3" />
              <span>Discard ({selectedIds.length})</span>
            </Button>

            <Button
              size="sm"
              variant="outline"
              onClick={handleExportBatch}
              className="h-8 gap-1.5 border-border text-xs font-mono"
            >
              <Download className="h-3 w-3 text-muted-foreground" />
              <span>Export Batch</span>
            </Button>
          </div>
        </div>

        {/* DLQ Table */}
        <div className="overflow-x-auto scrollbar-enterprise rounded-lg border border-border/60">
          <table className="w-full text-left text-xs font-mono">
            <thead>
              <tr className="border-b border-border/60 bg-muted/30 text-[11px] text-muted-foreground/70 uppercase">
                <th className="py-2.5 px-3 w-8">
                  <button
                    type="button"
                    onClick={toggleSelectAll}
                    className="flex items-center text-muted-foreground hover:text-foreground"
                  >
                    {selectedIds.length === displayRecords.length ? (
                      <CheckSquare className="h-4 w-4 text-primary" />
                    ) : (
                      <Square className="h-4 w-4" />
                    )}
                  </button>
                </th>
                <th className="py-2.5 px-3 font-semibold">Entity & Source Agent</th>
                <th className="py-2.5 px-3 font-semibold">Failure Classification</th>
                <th className="py-2.5 px-3 font-semibold">Error Reason</th>
                <th className="py-2.5 px-3 font-semibold text-center">Retries</th>
                <th className="py-2.5 px-3 font-semibold text-right">Quarantined At</th>
                <th className="py-2.5 px-3 font-semibold text-center">Payload</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50 text-[11px]">
              {displayRecords.map((r) => {
                const isSelected = selectedIds.includes(r.id);

                return (
                  <tr
                    key={r.id}
                    className={cn(
                      "hover:bg-muted/30 transition-colors",
                      isSelected && "bg-primary/5"
                    )}
                  >
                    <td className="py-3 px-3">
                      <button
                        type="button"
                        onClick={() => toggleSelect(r.id)}
                        className="flex items-center text-muted-foreground hover:text-foreground"
                      >
                        {isSelected ? (
                          <CheckSquare className="h-4 w-4 text-primary" />
                        ) : (
                          <Square className="h-4 w-4" />
                        )}
                      </button>
                    </td>

                    <td className="py-3 px-3">
                      <div className="font-semibold text-foreground">{r.record_identifier}</div>
                      <div className="text-[10px] text-muted-foreground/70 flex items-center gap-1.5">
                        <span className="uppercase text-[9px] bg-muted px-1 rounded">{r.entity_type}</span>
                        <span>{r.source_agent}</span>
                      </div>
                    </td>

                    <td className="py-3 px-3">
                      <Badge
                        variant="outline"
                        className={cn(
                          "font-mono text-[9px] py-0",
                          r.error_category === "SANCTION_MATCH" && "border-rose-500/30 bg-rose-500/10 text-rose-500",
                          r.error_category === "SCHEMA_VALIDATION" && "border-amber-500/30 bg-amber-500/10 text-amber-500",
                          r.error_category === "SMTP_TIMEOUT" && "border-cyan-500/30 bg-cyan-500/10 text-cyan-500",
                          r.error_category === "COLLISION" && "border-purple-500/30 bg-purple-500/10 text-purple-500"
                        )}
                      >
                        {r.error_category}
                      </Badge>
                    </td>

                    <td className="py-3 px-3 text-muted-foreground max-w-xs truncate" title={r.error_reason}>
                      {r.error_reason}
                    </td>

                    <td className="py-3 px-3 text-center tabular-nums font-bold text-foreground">
                      {r.retry_count}
                    </td>

                    <td className="py-3 px-3 text-right text-muted-foreground tabular-nums">
                      {new Date(r.quarantined_at).toLocaleTimeString()}
                    </td>

                    <td className="py-3 px-3 text-center">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setInspectRecord(r)}
                        className="h-6 px-2 text-[10px] gap-1 font-mono text-primary hover:bg-primary/10"
                      >
                        <Code2 className="h-3 w-3" />
                        Inspect
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Payload Modal */}
      {inspectRecord && (
        <Dialog open={Boolean(inspectRecord)} onOpenChange={(open) => !open && setInspectRecord(null)}>
          <DialogContent className="max-w-xl border-border bg-background p-6">
            <DialogHeader className="space-y-1">
              <DialogTitle className="text-base font-semibold flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-500" />
                Quarantined Record Diagnostic Inspection
              </DialogTitle>
              <DialogDescription className="text-xs text-muted-foreground font-mono">
                ID: {inspectRecord.id} — {inspectRecord.record_identifier}
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-3 py-2 text-xs font-mono">
              <div className="rounded border border-destructive/30 bg-destructive/5 p-2.5 text-destructive">
                <span className="font-bold">Error:</span> {inspectRecord.error_reason}
              </div>

              <div>
                <span className="text-[10px] uppercase font-semibold text-muted-foreground block mb-1">
                  Raw Working Payload
                </span>
                <div className="rounded-lg bg-zinc-950 p-4 border border-zinc-800 text-emerald-400 max-h-64 overflow-y-auto scrollbar-enterprise">
                  <pre>{JSON.stringify(inspectRecord.payload, null, 2)}</pre>
                </div>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}

