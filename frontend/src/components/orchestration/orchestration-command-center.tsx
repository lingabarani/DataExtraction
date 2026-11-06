"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import { useTelemetryCache } from "@/hooks/use-telemetry-cache";
import { toast } from "sonner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  HeaderStatusResponse,
  WorkflowStatusResponse,
  StartScrapingPayload,
  LiveKPIMetrics,
  QueueTelemetry,
  QueuesStatusResponse,
  TerminalLogEntry,
} from "./types";
import { CommandHeader } from "./header/command-header";
import { WorkflowControlBar } from "./header/workflow-control-bar";
import { StartScrapingModal } from "./modals/start-scraping-modal";
import { LiveKPIRibbon } from "./metrics/live-kpi-ribbon";
import { PipelineDAGView } from "./dag/pipeline-dag-view";
import { WorkflowStatusPanel } from "./dag/workflow-status-panel";
import { AgentStatusGrid } from "./agents/agent-status-grid";
import { WorkingLayerMonitor } from "./operations/working-layer-monitor";
import { PromotionGateFunnel } from "./operations/promotion-gate-funnel";
import { FreshnessSLADashboard } from "./operations/freshness-sla-dashboard";
import { QueueTelemetryMonitor } from "./operations/queue-telemetry-monitor";
import { OneReachDeliveryCenter } from "./operations/onereach-delivery-center";
import { LiveMonospaceTerminal } from "./terminal/live-monospace-terminal";
import { DLQErrorIsolationCenter } from "./terminal/dlq-error-isolation-center";
import {
  GitMerge,
  Layers,
  ListFilter,
  Send,
  Terminal,
} from "lucide-react";

export function OrchestrationCommandCenter() {
  const { header: cachedHeader, kpis: cachedKpis, queues: cachedQueues } = useTelemetryCache();

  // Instant 0ms initial state hydrated from in-memory SWR cache
  const [headerData, setHeaderData] = useState<HeaderStatusResponse | null>(() => ({
    status: "healthy",
    timestamp: new Date().toISOString(),
    platform: { status: cachedHeader.platform_status, latency_ms: 12 },
    temporal: {
      status: cachedHeader.temporal_status,
      endpoint: "localhost:7233",
      active_workflows: cachedHeader.active_workflows,
      pending_workflows: cachedHeader.pending_workflows,
    },
    database: {
      status: cachedHeader.database_status,
      master_records: cachedKpis.master_records,
      ping_ms: 4,
    },
    opensearch: {
      status: cachedHeader.opensearch_status,
      synced_documents: cachedKpis.opensearch_docs,
    },
    onereach: {
      status: cachedHeader.onereach_status,
      webhook_status: "ACTIVE",
    },
    telemetry: {
      active_workflows: cachedHeader.active_workflows,
      pending_workflows: cachedHeader.pending_workflows,
      last_successful_run: cachedHeader.last_successful_run
        ? {
            workflow_id: "wf-certified-golden",
            completed_at: cachedHeader.last_successful_run.timestamp,
            duration_seconds: cachedHeader.last_successful_run.duration_sec,
          }
        : null,
    },
  }));

  const [workflowStatus, setWorkflowStatus] = useState<WorkflowStatusResponse | null>(null);
  const [queuesData, setQueuesData] = useState<QueueTelemetry[]>(() =>
    cachedQueues.map((q) => ({
      id: q.id,
      name: q.name,
      agent: q.agent,
      workers: q.workers,
      pending: q.pending,
      running: q.running,
      completed: q.completed,
      failed: q.failed,
      retrying: q.retrying,
      avg_wait_ms: q.avg_wait_ms,
      status: q.status as QueueTelemetry["status"],
    }))
  );
  const [activeWorkflowId, setActiveWorkflowId] = useState<string | null>(null);
  const [selectedStageId, setSelectedStageId] = useState<string | null>("REGISTRY_INGESTION");
  const [logs, setLogs] = useState<TerminalLogEntry[]>([]);

  const [isLoadingHeader, setIsLoadingHeader] = useState(false);
  const [isSignaling, setIsSignaling] = useState(false);
  const [startModalOpen, setStartModalOpen] = useState(false);
  const [isStartingWorkflow, setIsStartingWorkflow] = useState(false);
  const [activeTab, setActiveTab] = useState<string>("topology");

  // Sync tab with URL hash for seamless top taskbar navigation
  useEffect(() => {
    const syncWithHash = () => {
      const hash = typeof window !== "undefined" ? window.location.hash.replace("#", "").toLowerCase() : "";
      if (!hash) return;
      if (hash === "observability" || hash === "terminal") {
        setActiveTab("terminal");
      } else if (hash === "onereach") {
        setActiveTab("onereach");
      } else if (hash === "freshness" || hash === "queues" || hash === "queues-sla") {
        setActiveTab("queues-sla");
      } else if (hash === "working-layer" || hash === "funnel") {
        setActiveTab("working-layer");
      } else if (hash === "topology" || hash === "orchestration") {
        setActiveTab("topology");
      }
    };
    syncWithHash();
    window.addEventListener("hashchange", syncWithHash);
    window.addEventListener("popstate", syncWithHash);
    return () => {
      window.removeEventListener("hashchange", syncWithHash);
      window.removeEventListener("popstate", syncWithHash);
    };
  }, []);

  const streamUnsubscribeRef = useRef<(() => void) | null>(null);

  // Default KPIs fallback hydrated dynamically from live telemetry cache
  const fallbackKpis: LiveKPIMetrics = {
    orgs_scraped: cachedKpis.orgs_scraped,
    employees_discovered: cachedKpis.employees_discovered,
    domains_verified: cachedKpis.domains_verified,
    identity_clusters: cachedKpis.identity_clusters,
    emails_found: cachedKpis.emails_found,
    emails_verified: cachedKpis.emails_verified,
    execs_found: cachedKpis.execs_found,
    employment_edges: cachedKpis.employment_edges,
    governance_approved: cachedKpis.governance_approved,
    promoted_records: cachedKpis.promoted_records,
    master_records: cachedKpis.master_records,
    opensearch_docs: cachedKpis.opensearch_docs,
    onereach_deliveries: cachedKpis.onereach_deliveries || 0,
  };

  // ── Fetch Header & Queues Status ──────────────────────────────────────────
  const fetchHeaderStatus = useCallback(async () => {
    setIsLoadingHeader(true);
    try {
      const [headerRes, queuesRes] = await Promise.allSettled([
        api.get<HeaderStatusResponse>("/orchestration/header/status"),
        api.get<QueuesStatusResponse>("/orchestration/queues/status"),
      ]);

      if (headerRes.status === "fulfilled") {
        setHeaderData(headerRes.value);
        if (headerRes.value.telemetry?.active_workflows > 0 && !activeWorkflowId) {
          fetchActiveWorkflow();
        }
      }

      if (queuesRes.status === "fulfilled" && queuesRes.value?.queues) {
        setQueuesData(queuesRes.value.queues);
      }
    } catch (err: unknown) {
      console.warn("Header/Queue status poll notice:", err);
    } finally {
      setIsLoadingHeader(false);
    }
  }, [activeWorkflowId]);

  // ── Fetch Active Workflow ─────────────────────────────────────────────────
  const fetchActiveWorkflow = useCallback(async () => {
    try {
      const res = await api.get<WorkflowStatusResponse>("/orchestration/active/status");
      if (res && res.workflow_id) {
        setActiveWorkflowId(res.workflow_id);
        setWorkflowStatus(res);
      }
    } catch {
      // Standby / idle cluster
    }
  }, []);

  // ── Setup SSE Stream when Workflow is Active ──────────────────────────────
  useEffect(() => {
    if (!activeWorkflowId) {
      if (streamUnsubscribeRef.current) {
        streamUnsubscribeRef.current();
        streamUnsubscribeRef.current = null;
      }
      return;
    }

    const unsubscribe = api.subscribeToStream(
      `/orchestration/${activeWorkflowId}/stream`,
      (event) => {
        if (event.data && typeof event.data === "object") {
          setWorkflowStatus((prev) => ({
            ...prev,
            ...event.data,
            workflow_id: activeWorkflowId,
          }));

          // Append live log if present
          if (event.data.log) {
            setLogs((prev) => [
              ...prev,
              {
                id: `stream_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
                timestamp: new Date().toISOString(),
                agent: event.data.log.agent || "SAGA MONITOR",
                message: event.data.log.message || "",
                type: event.data.log.type || "info",
              },
            ]);
          }
        }
      },
      (error) => {
        console.warn("SSE stream error, falling back to polling:", error);
      }
    );

    streamUnsubscribeRef.current = unsubscribe;

    return () => {
      if (streamUnsubscribeRef.current) {
        streamUnsubscribeRef.current();
        streamUnsubscribeRef.current = null;
      }
    };
  }, [activeWorkflowId]);

  // Initial load
  useEffect(() => {
    fetchHeaderStatus();
    const interval = setInterval(fetchHeaderStatus, 15000);
    return () => clearInterval(interval);
  }, [fetchHeaderStatus]);

  // ── Start Workflow Handler ────────────────────────────────────────────────
  const handleStartWorkflow = async (payload: StartScrapingPayload) => {
    setIsStartingWorkflow(true);
    try {
      const activeSources = Array.isArray(payload.sources)
        ? payload.sources
        : Object.entries(payload.sources || {})
            .filter(([_, enabled]) => enabled)
            .map(([k]) => k);

      const res = await api.post<{
        workflow_id: string;
        run_id: string;
        status: string;
        message: string;
      }>("/orchestration/start", {
        ...payload,
        sources: activeSources,
      });

      setActiveWorkflowId(res.workflow_id);
      setStartModalOpen(false);
      toast.success("Master Orchestration Saga Started", {
        description: `Workflow ID: ${res.workflow_id} dispatched to Temporal.`,
      });

      // Update local workflow state
      setWorkflowStatus({
        workflow_id: res.workflow_id,
        run_id: res.run_id,
        status: "RUNNING",
        current_stage: "REGISTRY_INGESTION",
        current_agent: "Agent 1 (Registry Harvester)",
        elapsed_seconds: 0,
        progress_pct: 5,
        current_queue: "registry-harvester",
        records_processed: 0,
        records_waiting: payload.data_count,
        failures_count: 0,
        retries_count: 0,
        stages: {
          REGISTRY_INGESTION: {
            id: "REGISTRY_INGESTION",
            name: "Registry Harvester",
            agent_num: 1,
            status: "RUNNING",
            duration_seconds: 1,
            records_in: payload.data_count,
            records_out: 0,
          },
        },
        kpis: fallbackKpis,
        agents: {},
      });

      // Add initiation log
      setLogs((prev) => [
        ...prev,
        {
          id: `log_init_${Date.now()}`,
          timestamp: new Date().toISOString(),
          agent: "SAGA MONITOR",
          message: `Dispatched new master saga: Target=${payload.data_count} records across [${payload.countries.join(", ")}], Mode=${payload.execution_mode}`,
          type: "info",
        },
      ]);

      fetchHeaderStatus();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to start workflow";
      toast.error("Failed to start workflow", { description: msg });
    } finally {
      setIsStartingWorkflow(false);
    }
  };

  // ── Signal Dispatcher Handler ─────────────────────────────────────────────
  const handleSignal = async (signalName: string) => {
    if (!activeWorkflowId) {
      toast.error("No active workflow to signal");
      return;
    }

    setIsSignaling(true);
    try {
      const res = await api.post<{
        workflow_id: string;
        signal: string;
        status: string;
        message: string;
      }>(`/orchestration/${activeWorkflowId}/signal`, {
        signal_name: signalName,
      });

      toast.success(`Signal ${signalName.toUpperCase()} Dispatched`, {
        description: res.message,
      });

      if (signalName === "pause") {
        setWorkflowStatus((prev) => prev ? { ...prev, status: "PAUSED" } : null);
      } else if (signalName === "resume") {
        setWorkflowStatus((prev) => prev ? { ...prev, status: "RUNNING" } : null);
      } else if (signalName === "emergency_halt" || signalName === "stop_workflow") {
        setWorkflowStatus((prev) => prev ? { ...prev, status: "TERMINATED" } : null);
      }

      setLogs((prev) => [
        ...prev,
        {
          id: `log_signal_${Date.now()}`,
          timestamp: new Date().toISOString(),
          agent: "OPERATOR",
          message: `Signal [${signalName.toUpperCase()}] broadcasted to Temporal workflow: ${activeWorkflowId}`,
          type: signalName === "emergency_halt" ? "error" : "warn",
        },
      ]);

      fetchHeaderStatus();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Signal transmission failed";
      toast.error(`Signal ${signalName} Failed`, { description: msg });
    } finally {
      setIsSignaling(false);
    }
  };

  const currentStages = workflowStatus?.stages ?? {};
  const currentKpis = workflowStatus?.kpis ?? fallbackKpis;
  const currentAgents = workflowStatus?.agents ?? {};

  return (
    <div className="flex flex-col min-h-screen bg-background text-foreground">

      {/* 2. Global Command Header */}
      <CommandHeader
        data={headerData}
        isLoading={isLoadingHeader}
        onRefresh={fetchHeaderStatus}
      />

      {/* 3. Action Control Bar */}
      <WorkflowControlBar
        workflowId={activeWorkflowId}
        workflowStatus={workflowStatus?.status ?? "IDLE"}
        onStartClick={() => setStartModalOpen(true)}
        onSignal={handleSignal}
        isSignaling={isSignaling}
      />

      {/* 4. Live 13-KPI Progression Ribbon */}
      <LiveKPIRibbon metrics={currentKpis} />

      {/* 5. Main Execution Space with Accessible Tabs */}
      <main className="flex-1 p-4 sm:p-6 space-y-6 max-w-[1600px] mx-auto w-full">
        <Tabs
          value={activeTab}
          onValueChange={(val) => {
            setActiveTab(val);
            if (typeof window !== "undefined") {
              const hashKey = val === "queues-sla" ? "freshness" : val === "terminal" ? "observability" : val;
              window.history.replaceState(null, "", `#${hashKey}`);
            }
          }}
          className="w-full space-y-6"
        >
          <div className="flex items-center justify-between border-b border-border/60 pb-2">
            <TabsList className="bg-muted/50 p-1">
              <TabsTrigger value="topology" className="text-xs gap-1.5 font-medium">
                <GitMerge className="h-3.5 w-3.5" />
                Topology & Execution
              </TabsTrigger>
              <TabsTrigger value="working-layer" className="text-xs gap-1.5 font-medium">
                <Layers className="h-3.5 w-3.5" />
                Working Layer & Funnels
              </TabsTrigger>
              <TabsTrigger value="queues-sla" className="text-xs gap-1.5 font-medium">
                <ListFilter className="h-3.5 w-3.5" />
                Queues & Freshness SLA
              </TabsTrigger>
              <TabsTrigger value="onereach" className="text-xs gap-1.5 font-medium">
                <Send className="h-3.5 w-3.5" />
                OneReach Outbound
              </TabsTrigger>
              <TabsTrigger value="terminal" className="text-xs gap-1.5 font-medium">
                <Terminal className="h-3.5 w-3.5" />
                Logs & Error Center
              </TabsTrigger>
            </TabsList>

            <span className="text-[11px] font-mono text-muted-foreground hidden md:inline-block">
              Single Source of Truth Vault: master_dataextraction
            </span>
          </div>

          {/* TAB 1: Topology & Execution */}
          <TabsContent value="topology" className="space-y-6 mt-0">
            {/* Pipeline Topological DAG */}
            <PipelineDAGView
              stages={currentStages}
              selectedStageId={selectedStageId}
              onSelectStage={(id) => setSelectedStageId(id)}
            />

            {/* Temporal Execution Telemetry Panel */}
            <WorkflowStatusPanel status={workflowStatus} />

            {/* 7 Distributed Agent Cards Grid */}
            <AgentStatusGrid agents={currentAgents} />
          </TabsContent>

          {/* TAB 2: Working Layer & Funnels */}
          <TabsContent value="working-layer" className="space-y-6 mt-0">
            {/* Pre-Master Working Layer Intelligence */}
            <WorkingLayerMonitor />

            {/* Promotion Gate Certification Funnel */}
            <PromotionGateFunnel />
          </TabsContent>

          {/* TAB 3: Queues & Freshness SLA */}
          <TabsContent value="queues-sla" className="space-y-6 mt-0">
            {/* Task Queue Telemetry Monitor */}
            <QueueTelemetryMonitor queues={queuesData} />

            {/* Freshness SLA Revalidation Dashboard */}
            <FreshnessSLADashboard />
          </TabsContent>

          {/* TAB 4: OneReach Outbound Delivery */}
          <TabsContent value="onereach" className="space-y-6 mt-0">
            {/* Outbound Delivery Center */}
            <OneReachDeliveryCenter />
          </TabsContent>

          {/* TAB 5: Terminal Logs & DLQ */}
          <TabsContent value="terminal" className="space-y-6 mt-0">
            {/* Live Monospace Execution Terminal */}
            <LiveMonospaceTerminal
              logs={logs}
              onClearLogs={() => setLogs([])}
              workflowId={activeWorkflowId}
            />

            {/* DLQ & Error Isolation Center */}
            <DLQErrorIsolationCenter />
          </TabsContent>
        </Tabs>
      </main>

      {/* Start Scraping Config Modal */}
      <StartScrapingModal
        open={startModalOpen}
        onOpenChange={setStartModalOpen}
        onSubmit={handleStartWorkflow}
        isSubmitting={isStartingWorkflow}
      />
    </div>
  );
}
