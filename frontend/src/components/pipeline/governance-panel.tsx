"use client";

import { useState, useEffect, useCallback } from "react";
import {
  ShieldCheck, ArrowRight, Zap, RefreshCw, AlertTriangle,
  CheckCircle2, Clock, Play, Lock, Eye, Check, AlertCircle,
  Database, Users, Mail, ArrowUpRight, Flame, BarChart3, Scale, Activity
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { toast } from "sonner";

interface GovernanceStats {
  status: string;
  timestamp: string;
  working_layer: {
    total_organizations: number;
    in_enrichment: number;
    approved_for_promotion: number;
    promoted_to_master: number;
    quarantined: number;
    revalidation_pending: number;
    total_persons: number;
    total_emails: number;
    email_deliverability_breakdown?: Record<string, number>;
  };
  master_vault: {
    total_organizations: number;
    average_quality_score: number;
    average_trust_score: number;
    average_freshness_score: number;
    overdue_revalidations: number;
    total_persons: number;
    total_verified_emails: number;
  };
  governance_gate: {
    certification_threshold_quality: number;
    certification_threshold_trust: number;
    quarantine_rate_percentage: number;
    dlq_pending_records: number;
  };
}

interface OverdueRecord {
  org_id: string;
  legal_name?: string;
  primary_domain?: string;
  freshness_score: number;
  overdue_dimensions: string[];
  recommended_actions: string[];
}

interface QuarantineRecord {
  org_id: string;
  legal_name: string;
  primary_domain?: string;
  data_quality_score: number;
  trust_score: number;
  governance_status: string;
  updated_at: string;
}

export function GovernancePanel() {
  const [stats, setStats] = useState<GovernanceStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [overdueList, setOverdueList] = useState<OverdueRecord[]>([]);
  const [quarantineList, setQuarantineList] = useState<QuarantineRecord[]>([]);

  // Dialog & Action States
  const [promoDialogOpen, setPromoDialogOpen] = useState(false);
  const [minQuality, setMinQuality] = useState(80);
  const [minTrust, setMinTrust] = useState(0.85);
  const [batchSize, setBatchSize] = useState(1000);
  const [promoting, setPromoting] = useState(false);

  const [sweepDialogOpen, setSweepDialogOpen] = useState(false);
  const [sweepBatchSize, setSweepBatchSize] = useState(5000);
  const [sweeping, setSweeping] = useState(false);

  // ── Fetch Telemetry ────────────────────────────────────────────────────────
  const fetchStats = useCallback(async () => {
    try {
      const data = await api.get<GovernanceStats>("/governance/stats");
      setStats(data);
    } catch (err: any) {
      console.warn("Governance stats fetch note:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchOverdue = useCallback(async () => {
    try {
      const res = await api.get<{ records: OverdueRecord[] }>("/governance/revalidation/overdue?limit=25");
      if (res && res.records) {
        setOverdueList(res.records);
      }
    } catch (err: any) {
      console.warn("Overdue list fetch note:", err);
    }
  }, []);

  const fetchQuarantine = useCallback(async () => {
    try {
      const res = await api.get<{ records: QuarantineRecord[] }>("/governance/quarantine/records?limit=25");
      if (res && res.records) {
        setQuarantineList(res.records);
      }
    } catch (err: any) {
      console.warn("Quarantine list fetch note:", err);
    }
  }, []);

  useEffect(() => {
    fetchStats();
    fetchOverdue();
    fetchQuarantine();
    const interval = setInterval(fetchStats, 10000);
    return () => clearInterval(interval);
  }, [fetchStats, fetchOverdue, fetchQuarantine]);

  // ── Execute Promotion Gate ─────────────────────────────────────────────────
  const handleExecutePromotion = async () => {
    setPromoting(true);
    try {
      const res = await api.post<{
        status: string;
        promotion_gate_outcome?: {
          promoted_orgs: number;
          promoted_persons: number;
          promoted_emails: number;
        };
      }>("/governance/promotion/trigger", {
        min_quality: minQuality,
        min_trust: minTrust,
        batch_size: batchSize,
        auto_evaluate_pre_master: true,
      });

      const outcome = res.promotion_gate_outcome;
      toast.success(
        `Atomic Promotion Gate Executed: Promoted ${outcome?.promoted_orgs || 0} Orgs, ${outcome?.promoted_persons || 0} Persons, ${outcome?.promoted_emails || 0} Verified Emails into Master Golden Vault!`
      );
      setPromoDialogOpen(false);
      fetchStats();
      fetchOverdue();
    } catch (err: any) {
      toast.error(`Promotion failed: ${err.message}`);
    } finally {
      setPromoting(false);
    }
  };

  // ── Execute Freshness & SLA Revalidation Sweep ─────────────────────────────
  const handleExecuteSweep = async () => {
    setSweeping(true);
    try {
      const res = await api.post<{
        status: string;
        freshness_decay?: { processed_count: number; average_freshness_score: number };
        overdue_detected: number;
        reharvest_staging?: { staged_count: number };
      }>("/governance/revalidation/sweep", {
        batch_size: sweepBatchSize,
        auto_reharvest: true,
      });

      toast.success(
        `Revalidation Sweep Completed: Decayed ${res.freshness_decay?.processed_count || 0} entities (Avg F: ${res.freshness_decay?.average_freshness_score || 1.0}). Detected ${res.overdue_detected || 0} overdue SLAs, staged ${res.reharvest_staging?.staged_count || 0} back for reharvest!`
      );
      setSweepDialogOpen(false);
      fetchStats();
      fetchOverdue();
    } catch (err: any) {
      toast.error(`Sweep failed: ${err.message}`);
    } finally {
      setSweeping(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* ── Top Action & Overview Header ───────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-4 rounded-xl border border-border bg-card/60 backdrop-blur-md shadow-sm">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-emerald-500" />
            <h3 className="text-base font-semibold text-foreground tracking-tight">
              Golden Master Vault & Autonomous Promotion Gate
            </h3>
            <Badge variant="outline" className="border-emerald-500/30 text-emerald-400 bg-emerald-500/10 font-mono text-[10px]">
              CERTIFIED GATE ACTIVE
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground">
            Strict MDM Single Source of Truth: Pre-master working canvas isolates raw enrichment. Only certified entities ($Q \ge 80, T \ge 0.85$, Sanctions CLEAR) enter Master Vault.
          </p>
        </div>

        <div className="flex items-center gap-2.5 shrink-0">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setSweepDialogOpen(true)}
            className="border-amber-500/30 text-amber-400 hover:bg-amber-500/10 hover:border-amber-500/50 text-xs font-medium"
          >
            <Clock className="w-3.5 h-3.5 mr-1.5" />
            Trigger SLA Revalidation
          </Button>

          <Button
            size="sm"
            onClick={() => setPromoDialogOpen(true)}
            className="bg-emerald-600 hover:bg-emerald-500 text-white shadow-sm text-xs font-medium"
          >
            <Zap className="w-3.5 h-3.5 mr-1.5" />
            Execute Promotion Gate
          </Button>
        </div>
      </div>

      {/* ── Metric Bento Grid ──────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Pre-Master Working Canvas */}
        <Card className="border-border bg-card/70 hover:border-foreground/20 transition-all">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Working Canvas (Pre-Master)
              </span>
              <Database className="w-4 h-4 text-cyan-400" />
            </div>
            <CardTitle className="text-2xl font-bold font-mono tracking-tight text-foreground">
              {stats?.working_layer?.total_organizations?.toLocaleString() ?? "0"}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="text-xs text-muted-foreground space-y-1">
              <div className="flex justify-between items-center">
                <span>In Enrichment:</span>
                <span className="font-mono text-zinc-300">{stats?.working_layer?.in_enrichment || 0}</span>
              </div>
              <div className="flex justify-between items-center text-emerald-400 font-medium">
                <span>Approved for Promotion:</span>
                <span className="font-mono">{stats?.working_layer?.approved_for_promotion || 0}</span>
              </div>
              <div className="flex justify-between items-center text-muted-foreground">
                <span>Working Contacts (P / E):</span>
                <span className="font-mono">{stats?.working_layer?.total_persons || 0} / {stats?.working_layer?.total_emails || 0}</span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Card 2: Master Vault Golden Records */}
        <Card className="border-emerald-500/20 bg-emerald-950/10 hover:border-emerald-500/40 transition-all">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-emerald-400">
                Master Vault Golden Entities
              </span>
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
            </div>
            <CardTitle className="text-2xl font-bold font-mono tracking-tight text-emerald-300">
              {stats?.master_vault?.total_organizations?.toLocaleString() ?? "0"}
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="text-xs text-muted-foreground space-y-1">
              <div className="flex justify-between items-center">
                <span>Avg Bayesian Quality:</span>
                <span className="font-mono text-emerald-300">{stats?.master_vault?.average_quality_score ?? 0}/100</span>
              </div>
              <div className="flex justify-between items-center">
                <span>Avg Bayesian Trust:</span>
                <span className="font-mono text-emerald-300">{(stats?.master_vault?.average_trust_score ?? 0.95).toFixed(4)}</span>
              </div>
              <div className="flex justify-between items-center text-zinc-400">
                <span>Certified Executives / Emails:</span>
                <span className="font-mono">{stats?.master_vault?.total_persons?.toLocaleString() || 0} / {stats?.master_vault?.total_verified_emails?.toLocaleString() || 0}</span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Card 3: Freshness & SLA Decay */}
        <Card className="border-border bg-card/70 hover:border-foreground/20 transition-all">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Continuous Freshness F(t)
              </span>
              <Flame className="w-4 h-4 text-amber-400" />
            </div>
            <CardTitle className="text-2xl font-bold font-mono tracking-tight text-foreground">
              {((stats?.master_vault?.average_freshness_score ?? 1.0) * 100).toFixed(1)}%
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="space-y-2">
              <Progress value={(stats?.master_vault?.average_freshness_score ?? 1.0) * 100} className="h-1.5" />
              <div className="flex justify-between items-center text-xs text-muted-foreground">
                <span>Overdue Revalidations:</span>
                <span className={`font-mono font-medium ${stats?.master_vault?.overdue_revalidations ? 'text-amber-400' : 'text-zinc-400'}`}>
                  {stats?.master_vault?.overdue_revalidations || 0} records
                </span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Card 4: Quarantine & DLQ Isolation */}
        <Card className="border-border bg-card/70 hover:border-foreground/20 transition-all">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Quarantine & DLQ Gate
              </span>
              <AlertTriangle className="w-4 h-4 text-amber-500" />
            </div>
            <CardTitle className="text-2xl font-bold font-mono tracking-tight text-foreground">
              {stats?.governance_gate?.quarantine_rate_percentage ?? 0}%
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="text-xs text-muted-foreground space-y-1">
              <div className="flex justify-between items-center">
                <span>Quarantined Leads:</span>
                <span className="font-mono text-amber-400">{stats?.working_layer?.quarantined || 0}</span>
              </div>
              <div className="flex justify-between items-center">
                <span>DLQ Pending Queue:</span>
                <span className="font-mono text-zinc-300">{stats?.governance_gate?.dlq_pending_records || 0}</span>
              </div>
              <div className="flex justify-between items-center text-[10px] text-zinc-500">
                <span>Thresholds:</span>
                <span className="font-mono">Quality ≥ 80 | Trust ≥ 0.85</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ── Architecture Pipeline Flow Visualizer ──────────────────────────── */}
      <Card className="border-border bg-card/50">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <Activity className="w-4 h-4 text-primary" />
            Approved MDM Promotion Pipeline Topology
          </CardTitle>
          <CardDescription className="text-xs">
            Data flows left-to-right through Pre-Master enrichment. The Atomic Promotion Gate safeguards the Master Vault from dirty or unverified writes.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-5 gap-3 text-xs">
            {/* Step 1 */}
            <div className="p-3 rounded-lg border border-border bg-card/80 space-y-1.5">
              <div className="flex items-center justify-between font-mono text-[11px] text-zinc-400">
                <span>01. HARVEST</span>
                <Badge variant="outline" className="text-[9px]">RAW</Badge>
              </div>
              <p className="font-semibold text-foreground">Harvesters 1 & 2</p>
              <p className="text-muted-foreground text-[11px]">Sovereign registries, state filings, Google Places & OSM</p>
            </div>

            {/* Step 2 */}
            <div className="p-3 rounded-lg border border-cyan-500/30 bg-cyan-950/10 space-y-1.5">
              <div className="flex items-center justify-between font-mono text-[11px] text-cyan-400">
                <span>02. ENRICH</span>
                <Badge variant="outline" className="text-[9px] border-cyan-500/40 text-cyan-300">PRE-MASTER</Badge>
              </div>
              <p className="font-semibold text-foreground">Working Canvas</p>
              <p className="text-muted-foreground text-[11px]">Splink 5.0 resolution, Agent 7 SMTP verification, Agent 4 Execs</p>
            </div>

            {/* Step 3 */}
            <div className="p-3 rounded-lg border border-amber-500/40 bg-amber-950/15 space-y-1.5">
              <div className="flex items-center justify-between font-mono text-[11px] text-amber-400">
                <span>03. CERTIFY</span>
                <Badge variant="outline" className="text-[9px] border-amber-500/50 text-amber-300">GATE</Badge>
              </div>
              <p className="font-semibold text-foreground">Agent 5 Governance</p>
              <p className="text-muted-foreground text-[11px]">Bayesian Quality ≥ 80, Trust ≥ 0.85, Sanctions Clear. Else DLQ.</p>
            </div>

            {/* Step 4 */}
            <div className="p-3 rounded-lg border border-emerald-500/40 bg-emerald-950/20 space-y-1.5">
              <div className="flex items-center justify-between font-mono text-[11px] text-emerald-400">
                <span>04. MASTER VAULT</span>
                <Badge variant="outline" className="text-[9px] border-emerald-500/50 text-emerald-300">GOLDEN</Badge>
              </div>
              <p className="font-semibold text-emerald-300">Certified Vault</p>
              <p className="text-muted-foreground text-[11px]">Atomic CTE commit. Freshness stamped 1.0000, SLA set for +90d</p>
            </div>

            {/* Step 5 */}
            <div className="p-3 rounded-lg border border-border bg-card/80 space-y-1.5">
              <div className="flex items-center justify-between font-mono text-[11px] text-zinc-400">
                <span>05. OUTBOUND</span>
                <Badge variant="outline" className="text-[9px]">DELIVERY</Badge>
              </div>
              <p className="font-semibold text-foreground">Agent 6 & OneReach</p>
              <p className="text-muted-foreground text-[11px]">OpenSearch 2.x CDC sync, Knowledge Graph, HMAC webhook push</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── Two Columns: Overdue SLAs & Quarantined Leads ───────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left Column: Overdue SLAs */}
        <Card className="border-border">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-sm font-semibold flex items-center gap-2">
                  <Clock className="w-4 h-4 text-amber-400" />
                  Overdue SLA Revalidations
                </CardTitle>
                <CardDescription className="text-xs">
                  Master records requiring dimension-specific verification sweeps
                </CardDescription>
              </div>
              <Badge variant="outline" className="text-xs font-mono">
                {overdueList.length} Active Stale
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="pt-0">
            {overdueList.length === 0 ? (
              <div className="p-8 text-center text-xs text-muted-foreground border border-dashed rounded-lg">
                <CheckCircle2 className="w-6 h-6 text-emerald-500 mx-auto mb-2 opacity-60" />
                All Master Vault entity dimensions are strictly within SLA limits (Website &lt;30d, Email &lt;90d, Exec &lt;90d).
              </div>
            ) : (
              <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
                {overdueList.map((rec) => (
                  <div
                    key={rec.org_id}
                    className="p-3 rounded-lg border border-border bg-card/60 hover:border-amber-500/30 transition-colors flex items-center justify-between gap-3 text-xs"
                  >
                    <div className="space-y-0.5 min-w-0">
                      <p className="font-medium text-foreground truncate">
                        {rec.legal_name || rec.primary_domain || rec.org_id}
                      </p>
                      <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                        <span>Domain: {rec.primary_domain || "N/A"}</span>
                        <span>•</span>
                        <span className="font-mono text-amber-400">
                          Freshness: {(rec.freshness_score * 100).toFixed(0)}%
                        </span>
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {rec.overdue_dimensions?.map((dim) => (
                        <Badge key={dim} variant="secondary" className="text-[10px] uppercase font-mono bg-amber-500/10 text-amber-400 border border-amber-500/20">
                          {dim}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Right Column: Quarantined Leads */}
        <Card className="border-border">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-sm font-semibold flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 text-rose-400" />
                  Quarantined Isolation Records
                </CardTitle>
                <CardDescription className="text-xs">
                  Leads isolated by Agent 5 Certification Gate failing Quality or Trust
                </CardDescription>
              </div>
              <Badge variant="outline" className="text-xs font-mono text-rose-400 border-rose-500/30">
                {quarantineList.length} Quarantined
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="pt-0">
            {quarantineList.length === 0 ? (
              <div className="p-8 text-center text-xs text-muted-foreground border border-dashed rounded-lg">
                <ShieldCheck className="w-6 h-6 text-emerald-500 mx-auto mb-2 opacity-60" />
                Zero records currently quarantined in working canvas. All evaluated records met certification thresholds.
              </div>
            ) : (
              <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
                {quarantineList.map((rec) => (
                  <div
                    key={rec.org_id}
                    className="p-3 rounded-lg border border-border bg-card/60 hover:border-rose-500/30 transition-colors flex items-center justify-between gap-3 text-xs"
                  >
                    <div className="space-y-0.5 min-w-0">
                      <p className="font-medium text-foreground truncate">
                        {rec.legal_name || rec.primary_domain || rec.org_id}
                      </p>
                      <p className="text-[11px] text-muted-foreground font-mono">
                        Domain: {rec.primary_domain || "unregistered"} • ID: {rec.org_id.slice(0, 16)}...
                      </p>
                    </div>
                    <div className="text-right shrink-0">
                      <Badge variant="outline" className="text-[10px] font-mono border-rose-500/40 text-rose-400 bg-rose-500/10">
                        Q: {rec.data_quality_score} | T: {Number(rec.trust_score || 0).toFixed(2)}
                      </Badge>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ── Execute Promotion Dialog ───────────────────────────────────────── */}
      <Dialog open={promoDialogOpen} onOpenChange={setPromoDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Zap className="w-5 h-5 text-emerald-500" />
              Execute Atomic Promotion Gate
            </DialogTitle>
            <DialogDescription className="text-xs text-muted-foreground">
              Promotes verified records from <code>staging_dataextraction.working_*</code> to <code>master_dataextraction.*</code> in a single ACID transaction.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-3 text-xs">
            <div className="space-y-1.5">
              <label className="font-semibold text-foreground flex justify-between">
                <span>Minimum Bayesian Quality Score (0 - 100):</span>
                <span className="font-mono text-emerald-400">{minQuality}</span>
              </label>
              <input
                type="range"
                min="50"
                max="100"
                step="5"
                value={minQuality}
                onChange={(e) => setMinQuality(Number(e.target.value))}
                className="w-full accent-emerald-500 cursor-pointer"
              />
            </div>

            <div className="space-y-1.5">
              <label className="font-semibold text-foreground flex justify-between">
                <span>Minimum Bayesian Trust Score (0.00 - 1.00):</span>
                <span className="font-mono text-emerald-400">{minTrust.toFixed(2)}</span>
              </label>
              <input
                type="range"
                min="0.50"
                max="1.00"
                step="0.05"
                value={minTrust}
                onChange={(e) => setMinTrust(Number(e.target.value))}
                className="w-full accent-emerald-500 cursor-pointer"
              />
            </div>

            <div className="space-y-1.5">
              <label className="font-semibold text-foreground flex justify-between">
                <span>Batch Size:</span>
                <span className="font-mono text-zinc-300">{batchSize} records</span>
              </label>
              <input
                type="number"
                min="100"
                max="10000"
                step="100"
                value={batchSize}
                onChange={(e) => setBatchSize(Number(e.target.value))}
                className="w-full p-2 rounded border border-border bg-background font-mono text-xs"
              />
            </div>

            <div className="p-3 rounded-lg border border-emerald-500/20 bg-emerald-950/20 text-emerald-300 text-[11px] space-y-1">
              <p className="font-semibold flex items-center gap-1.5">
                <ShieldCheck className="w-3.5 h-3.5" /> Promotion Invariants Enforced:
              </p>
              <ul className="list-disc list-inside space-y-0.5 text-zinc-400">
                <li>Freshness initialized to 1.0000</li>
                <li>Next verification scheduled for NOW() + 90 days</li>
                <li>Working entities updated to &apos;PROMOTED&apos; atomically</li>
              </ul>
            </div>
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" size="sm" onClick={() => setPromoDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={promoting}
              onClick={handleExecutePromotion}
              className="bg-emerald-600 hover:bg-emerald-500 text-white"
            >
              {promoting ? "Executing Multi-Table CTE..." : "Execute Atomic Promotion"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Trigger Sweep Dialog ───────────────────────────────────────────── */}
      <Dialog open={sweepDialogOpen} onOpenChange={setSweepDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Clock className="w-5 h-5 text-amber-500" />
              Trigger Freshness & SLA Revalidation Sweep
            </DialogTitle>
            <DialogDescription className="text-xs text-muted-foreground">
              Applies continuous exponential decay $F(t) = \exp(-\lambda \cdot \Delta t)$ across the Master Vault and stages expired SLAs into the working layer for reharvest.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-3 text-xs">
            <div className="space-y-1.5">
              <label className="font-semibold text-foreground flex justify-between">
                <span>Sweep Batch Size:</span>
                <span className="font-mono text-amber-400">{sweepBatchSize} master records</span>
              </label>
              <input
                type="number"
                min="500"
                max="25000"
                step="500"
                value={sweepBatchSize}
                onChange={(e) => setSweepBatchSize(Number(e.target.value))}
                className="w-full p-2 rounded border border-border bg-background font-mono text-xs"
              />
            </div>

            <div className="p-3 rounded-lg border border-amber-500/20 bg-amber-950/20 text-amber-300 text-[11px] space-y-1">
              <p className="font-semibold flex items-center gap-1.5">
                <Flame className="w-3.5 h-3.5" /> Continuous SLA Decay Rules:
              </p>
              <ul className="list-disc list-inside space-y-0.5 text-zinc-400">
                <li>Website Content: 30-Day SLA ($\lambda = 0.0231$)</li>
                <li>Email Deliverability: 90-Day SLA ($\lambda = 0.0077$)</li>
                <li>Executive Hierarchy: 90-Day SLA ($\lambda = 0.0077$)</li>
                <li>Auto-Reharvest: Overdue records staged to working layer with REVALIDATION_PENDING</li>
              </ul>
            </div>
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" size="sm" onClick={() => setSweepDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={sweeping}
              onClick={handleExecuteSweep}
              className="bg-amber-600 hover:bg-amber-500 text-white"
            >
              {sweeping ? "Calculating Continuous Decay..." : "Execute Revalidation Sweep"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

