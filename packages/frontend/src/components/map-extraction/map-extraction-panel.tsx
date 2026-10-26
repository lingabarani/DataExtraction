"use client";

import React, { useState, useEffect, useCallback, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  MapPin,
  Layers,
  Activity,
  Play,
  Square,
  RefreshCw,
  Server,
  Database,
  Download,
  Settings,
  ShieldCheck,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  Search,
  ExternalLink,
  ChevronRight,
  Code2,
  FileSpreadsheet,
  Terminal,
  Zap,
  Sliders,
  Filter,
  Check,
} from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import { api } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ActiveJob {
  task_id: string;
  state?: string;
  field?: string;
  started_at: string;
  status: string;
}

interface ExtractionStatus {
  status: string;
  total_states: number;
  completed_states_count: number;
  completed_states: string[];
  total_records_collected: number;
  total_chunks_processed: number;
  active_jobs_count: number;
  active_jobs: ActiveJob[];
  sqlite_db_path?: string;
}

interface StateItem {
  name: string;
  code: string;
  bbox: {
    min_lat: number;
    min_lon: number;
    max_lat: number;
    max_lon: number;
  };
  estimated_chunks: number;
  is_completed: boolean;
}

interface FieldItem {
  field: string;
  category_group: string;
  description: string;
  query_template: string;
}

interface MirrorItem {
  url: string;
  is_healthy: boolean;
  is_active: boolean;
  consecutive_failures: number;
  total_failures: number;
  total_successes: number;
  last_status_code: number | null;
  cooldown_remaining_sec: number;
  last_error_message: string | null;
  latency_ms?: number;
}

interface MirrorsResponse {
  total_mirrors: number;
  healthy_mirrors: number;
  active_mirror: string;
  mirrors: MirrorItem[];
}

interface OverpassConfigData {
  primary_endpoint: string;
  fallback_endpoints: string[];
  custom_endpoint: string | null;
  connect_timeout_sec: number;
  read_timeout_sec: number;
  query_server_timeout_sec: number;
  max_retries: number;
  backoff_factor: number;
  circuit_breaker_cooldown_sec: number;
  enable_adaptive_subdivision: boolean;
  max_quadtree_depth: number;
  chunk_size_deg: number;
  min_chunk_deg: number;
  rate_limit_delay_sec: number;
  contact_email: string;
  user_agent: string;
}

// ── Main Component ────────────────────────────────────────────────────────────

export function MapExtractionPanel() {
  // Navigation & Tabs
  const [activeTab, setActiveTab] = useState("states");

  // Core Data States
  const [statusData, setStatusData] = useState<ExtractionStatus | null>(null);
  const [statesList, setStatesList] = useState<StateItem[]>([]);
  const [fieldsList, setFieldsList] = useState<FieldItem[]>([]);
  const [mirrorsData, setMirrorsData] = useState<MirrorsResponse | null>(null);
  const [configData, setConfigData] = useState<OverpassConfigData | null>(null);

  // Loading & Action States
  const [isLoading, setIsLoading] = useState(true);
  const [isProbingMirrors, setIsProbingMirrors] = useState(false);
  const [isStartingJob, setIsStartingJob] = useState(false);
  const [isStoppingJob, setIsStoppingJob] = useState(false);
  const [isIngesting, setIsIngesting] = useState(false);
  const [isReconciling, setIsReconciling] = useState(false);
  const [isSavingConfig, setIsSavingConfig] = useState(false);

  // Filters & User Selections
  const [stateSearch, setStateSearch] = useState("");
  const [stateStatusFilter, setStateStatusFilter] = useState<"all" | "completed" | "pending">("all");
  const [selectedFieldForPreview, setSelectedFieldForPreview] = useState<FieldItem | null>(null);

  // Execution modal state
  const [selectedStateForRun, setSelectedStateForRun] = useState("Alabama");
  const [selectedFieldForRun, setSelectedFieldForRun] = useState("healthcare");
  const [chunkSizeInput, setChunkSizeInput] = useState("0.5");
  const [resumeCheck, setResumeCheck] = useState(true);
  const [retryAffectedCheck, setRetryAffectedCheck] = useState(false);

  // Ingest modal state
  const [ingestState, setIngestState] = useState("Alabama");
  const [ingestField, setIngestField] = useState("healthcare");
  const [ingestDryRun, setIngestDryRun] = useState(false);

  // Fetch all initial data
  const loadData = useCallback(async (quiet = false) => {
    if (!quiet) setIsLoading(true);
    try {
      const [statusRes, statesRes, fieldsRes, mirrorsRes, configRes] = await Promise.all([
        api.get<ExtractionStatus>("/map-extraction/status").catch(() => null),
        api.get<{ states: StateItem[] }>("/map-extraction/states").catch(() => null),
        api.get<{ fields: FieldItem[] }>("/map-extraction/fields").catch(() => null),
        api.get<MirrorsResponse>("/map-extraction/mirrors").catch(() => null),
        api.get<OverpassConfigData>("/map-extraction/config").catch(() => null),
      ]);

      if (statusRes) setStatusData(statusRes);
      if (statesRes?.states) setStatesList(statesRes.states);
      if (fieldsRes?.fields) {
        setFieldsList(fieldsRes.fields);
        if (!selectedFieldForPreview && fieldsRes.fields.length > 0) {
          setSelectedFieldForPreview(fieldsRes.fields[0]);
        }
      }
      if (mirrorsRes) setMirrorsData(mirrorsRes);
      if (configRes) {
        setConfigData(configRes);
        setChunkSizeInput(String(configRes.chunk_size_deg));
      }
    } catch (err) {
      console.error("Failed to load map extraction telemetry:", err);
      if (!quiet) toast.error("Could not load extraction engine status.");
    } finally {
      if (!quiet) setIsLoading(false);
    }
  }, [selectedFieldForPreview]);

  useEffect(() => {
    loadData();
    // Poll telemetry every 6 seconds
    const interval = setInterval(() => loadData(true), 6000);
    return () => clearInterval(interval);
  }, [loadData]);

  // ── Actions ─────────────────────────────────────────────────────────────────

  const handleProbeMirrors = async () => {
    setIsProbingMirrors(true);
    toast.info("Probing all Overpass mirrors with live ping...");
    try {
      const res = await api.post<{
        probed_count: number;
        results: Array<{ url: string; latency_ms: number; status_code: number; is_healthy: boolean }>;
      }>("/map-extraction/mirrors/test", {});

      const latencyMap = new Map(res.results.map((r) => [r.url, r.latency_ms]));

      setMirrorsData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          mirrors: prev.mirrors.map((m) => ({
            ...m,
            latency_ms: latencyMap.get(m.url) ?? m.latency_ms,
          })),
        };
      });

      toast.success(`Successfully probed ${res.probed_count} mirror endpoints!`);
      loadData(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Mirror probe failed: ${msg}`);
    } finally {
      setIsProbingMirrors(false);
    }
  };

  const handleStartExtraction = async () => {
    setIsStartingJob(true);
    try {
      const res = await api.post<{
        status: string;
        task_id: string;
        states: string;
        fields: string;
        started_at: string;
      }>("/map-extraction/start", {
        state: selectedStateForRun,
        field: selectedFieldForRun,
        chunk_size_deg: parseFloat(chunkSizeInput) || 0.5,
        resume: resumeCheck,
        retry_affected: retryAffectedCheck,
      });

      toast.success(`Extraction launched! Task ID: ${res.task_id}`);
      loadData(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Failed to launch extraction: ${msg}`);
    } finally {
      setIsStartingJob(false);
    }
  };

  const handleStopExtraction = async (taskId?: string) => {
    setIsStoppingJob(true);
    try {
      await api.post("/map-extraction/stop", { task_id: taskId });
      toast.success("Extraction subprocess stopped gracefully.");
      loadData(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Failed to stop extraction: ${msg}`);
    } finally {
      setIsStoppingJob(false);
    }
  };

  const handleIngest = async () => {
    setIsIngesting(true);
    toast.info(`Ingesting ${ingestState} (${ingestField}) into OneExtraction DB...`);
    try {
      const res = await api.post<{
        status: string;
        stats: {
          inserted: number;
          updated: number;
          skipped: number;
          errors: number;
          total_normalized: number;
          dry_run: boolean;
        };
      }>("/map-extraction/ingest", {
        state: ingestState,
        field: ingestField,
        dry_run: ingestDryRun,
      });

      const s = res.stats;
      if (s.dry_run) {
        toast.success(`Dry Run Validated: ${s.total_normalized} valid records without writing.`);
      } else {
        toast.success(
          `Ingested ${s.inserted} new companies, updated ${s.updated}, skipped ${s.skipped} duplicate matches.`
        );
      }
      loadData(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Ingestion failed: ${msg}`);
    } finally {
      setIsIngesting(false);
    }
  };

  const handleReconcile = async () => {
    setIsReconciling(true);
    toast.info("Auditing disk files against SQLite WAL checkpoint database...");
    try {
      const res = await api.post<{
        status: string;
        report: { states_inspected: number; exports_found: number; updated_records: number };
      }>("/map-extraction/reconcile", { dry_run: false });

      toast.success(
        `Reconciled ${res.report.states_inspected} state directories, found ${res.report.exports_found} exports, repaired ${res.report.updated_records} records.`
      );
      loadData(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Reconciliation failed: ${msg}`);
    } finally {
      setIsReconciling(false);
    }
  };

  const handleDownload = async (stateName: string, fieldName: string, format: "json" | "csv") => {
    try {
      toast.info(`Downloading ${stateName} ${fieldName} (${format.toUpperCase()})...`);
      const filename = `osm_${stateName.toLowerCase()}_${fieldName}.${format}`;
      await api.download(`/map-extraction/export/${stateName}/${fieldName}?format=${format}`, filename);
      toast.success(`Download ready: ${filename}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Export download failed: ${msg}`);
    }
  };

  const handleSaveConfig = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!configData) return;
    setIsSavingConfig(true);

    try {
      const form = new FormData(e.currentTarget);
      const payload = {
        connect_timeout_sec: parseInt(form.get("connect_timeout_sec") as string, 10),
        read_timeout_sec: parseInt(form.get("read_timeout_sec") as string, 10),
        circuit_breaker_cooldown_sec: parseFloat(form.get("circuit_breaker_cooldown_sec") as string),
        max_quadtree_depth: parseInt(form.get("max_quadtree_depth") as string, 10),
        chunk_size_deg: parseFloat(form.get("chunk_size_deg") as string),
        rate_limit_delay_sec: parseFloat(form.get("rate_limit_delay_sec") as string),
        contact_email: form.get("contact_email") as string,
      };

      const res = await api.put<{ config: OverpassConfigData }>("/map-extraction/config", payload);
      setConfigData(res.config);
      toast.success("Runtime configuration saved successfully!");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`Failed to update config: ${msg}`);
    } finally {
      setIsSavingConfig(false);
    }
  };

  // ── Filtered States ─────────────────────────────────────────────────────────

  const filteredStates = useMemo(() => {
    return statesList.filter((s) => {
      const matchesSearch =
        s.name.toLowerCase().includes(stateSearch.toLowerCase()) ||
        s.code.toLowerCase().includes(stateSearch.toLowerCase());
      if (!matchesSearch) return false;

      if (stateStatusFilter === "completed") return s.is_completed;
      if (stateStatusFilter === "pending") return !s.is_completed;
      return true;
    });
  }, [statesList, stateSearch, stateStatusFilter]);

  // Derived progress percentages
  const progressPct = statusData
    ? Math.round((statusData.completed_states_count / 50) * 100)
    : 0;

  return (
    <div className="space-y-6 p-6 max-w-[1600px] mx-auto">
      {/* ── Top Header & Hero ──────────────────────────────────────────────── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-2 border-b border-border">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-500">
              <MapPin className="w-5 h-5" />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
                Open Map Extraction Engine
                <Badge variant="outline" className="text-xs bg-emerald-500/10 text-emerald-500 border-emerald-500/30 font-medium">
                  v2.0 Enterprise
                </Badge>
              </h1>
              <p className="text-xs text-muted-foreground mt-0.5">
                Fault-tolerant OpenStreetMap POI extraction, Overpass mirror pool rotation, quadtree spatial subdivision & database deduplication.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => loadData()}
            disabled={isLoading}
            className="gap-2 text-xs"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
            Refresh
          </Button>

          {statusData && statusData.active_jobs_count > 0 ? (
            <Button
              variant="destructive"
              size="sm"
              onClick={() => handleStopExtraction()}
              disabled={isStoppingJob}
              className="gap-2 text-xs"
            >
              <Square className="w-3.5 h-3.5 fill-current" />
              Stop Active Job
            </Button>
          ) : (
            <Dialog>
              <DialogTrigger asChild>
                <Button size="sm" className="gap-2 text-xs bg-emerald-600 hover:bg-emerald-700 text-white shadow-sm">
                  <Play className="w-3.5 h-3.5 fill-current" />
                  Launch Extraction
                </Button>
              </DialogTrigger>
              <DialogContent className="sm:max-w-[480px]">
                <DialogHeader>
                  <DialogTitle className="flex items-center gap-2 text-lg">
                    <Play className="w-4 h-4 text-emerald-500" />
                    Start Extraction Job
                  </DialogTitle>
                  <DialogDescription>
                    Launches a managed background collection task across the Overpass mirror pool.
                  </DialogDescription>
                </DialogHeader>

                <div className="space-y-4 py-2">
                  <div className="space-y-1.5">
                    <Label className="text-xs">Select Target State</Label>
                    <Select value={selectedStateForRun} onValueChange={setSelectedStateForRun}>
                      <SelectTrigger className="text-xs">
                        <SelectValue placeholder="Choose a US State" />
                      </SelectTrigger>
                      <SelectContent className="max-h-56">
                        {statesList.map((st) => (
                          <SelectItem key={st.name} value={st.name} className="text-xs">
                            {st.name} ({st.code}) {st.is_completed ? "✓" : ""}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1.5">
                    <Label className="text-xs">Target Category / Field</Label>
                    <Select value={selectedFieldForRun} onValueChange={setSelectedFieldForRun}>
                      <SelectTrigger className="text-xs">
                        <SelectValue placeholder="Select POI Category" />
                      </SelectTrigger>
                      <SelectContent className="max-h-56">
                        {fieldsList.map((f) => (
                          <SelectItem key={f.field} value={f.field} className="text-xs">
                            {f.field.toUpperCase()} — {f.category_group}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1.5">
                    <Label className="text-xs">Grid Chunk Size (degrees)</Label>
                    <Input
                      type="number"
                      step="0.05"
                      min="0.1"
                      max="2.0"
                      value={chunkSizeInput}
                      onChange={(e) => setChunkSizeInput(e.target.value)}
                      className="text-xs font-mono"
                    />
                    <p className="text-[11px] text-muted-foreground">
                      Default is 0.5°. Smaller chunks (0.25°) reduce Overpass query load in dense metro areas.
                    </p>
                  </div>

                  <div className="flex items-center gap-6 pt-2">
                    <label className="flex items-center gap-2 text-xs cursor-pointer">
                      <input
                        type="checkbox"
                        checked={resumeCheck}
                        onChange={(e) => setResumeCheck(e.target.checked)}
                        className="rounded border-border"
                      />
                      Resume from checkpoint
                    </label>

                    <label className="flex items-center gap-2 text-xs cursor-pointer">
                      <input
                        type="checkbox"
                        checked={retryAffectedCheck}
                        onChange={(e) => setRetryAffectedCheck(e.target.checked)}
                        className="rounded border-border"
                      />
                      Retry failed / split chunks
                    </label>
                  </div>
                </div>

                <DialogFooter className="gap-2 sm:gap-0">
                  <Button
                    onClick={handleStartExtraction}
                    disabled={isStartingJob}
                    className="w-full text-xs bg-emerald-600 hover:bg-emerald-700 text-white"
                  >
                    {isStartingJob ? "Starting..." : "Begin Extraction"}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          )}
        </div>
      </div>

      {/* ── Key Telemetry Stat Cards ────────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Completed States */}
        <Card className="bg-card/70 border-border/80 backdrop-blur-sm shadow-xs">
          <CardHeader className="pb-2 flex flex-row items-center justify-between space-y-0">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              States Completed
            </span>
            <MapPin className="w-4 h-4 text-emerald-500" />
          </CardHeader>
          <CardContent>
            <div className="flex items-baseline justify-between">
              <div className="text-2xl font-bold font-mono tracking-tight text-foreground">
                {statusData?.completed_states_count ?? 0}
                <span className="text-xs text-muted-foreground font-normal ml-1">/ 50</span>
              </div>
              <Badge variant="secondary" className="text-xs font-mono">
                {progressPct}%
              </Badge>
            </div>
            <Progress value={progressPct} className="h-1.5 mt-3 bg-muted" />
          </CardContent>
        </Card>

        {/* Card 2: Total Records Collected */}
        <Card className="bg-card/70 border-border/80 backdrop-blur-sm shadow-xs">
          <CardHeader className="pb-2 flex flex-row items-center justify-between space-y-0">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              Records Extracted
            </span>
            <Database className="w-4 h-4 text-blue-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono tracking-tight text-foreground">
              {(statusData?.total_records_collected ?? 0).toLocaleString()}
            </div>
            <p className="text-[11px] text-muted-foreground mt-2 flex items-center gap-1">
              <span className="text-blue-500 font-medium">100% Free OSM Data</span> across 13 business categories
            </p>
          </CardContent>
        </Card>

        {/* Card 3: Overpass Mirror Pool */}
        <Card className="bg-card/70 border-border/80 backdrop-blur-sm shadow-xs">
          <CardHeader className="pb-2 flex flex-row items-center justify-between space-y-0">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              Mirror Pool Health
            </span>
            <Server className="w-4 h-4 text-indigo-500" />
          </CardHeader>
          <CardContent>
            <div className="flex items-baseline justify-between">
              <div className="text-2xl font-bold font-mono tracking-tight text-foreground">
                {mirrorsData?.healthy_mirrors ?? 0}
                <span className="text-xs text-muted-foreground font-normal ml-1">
                  / {mirrorsData?.total_mirrors ?? 4}
                </span>
              </div>
              <Badge
                variant="outline"
                className={`text-xs ${
                  (mirrorsData?.healthy_mirrors ?? 0) === (mirrorsData?.total_mirrors ?? 4)
                    ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/30"
                    : "bg-amber-500/10 text-amber-500 border-amber-500/30"
                }`}
              >
                Circuit Breaker Active
              </Badge>
            </div>
            <p className="text-[11px] text-muted-foreground mt-2 truncate">
              Active: {mirrorsData?.active_mirror ? new URL(mirrorsData.active_mirror).hostname : "Rotating..."}
            </p>
          </CardContent>
        </Card>

        {/* Card 4: Active Job Execution */}
        <Card className="bg-card/70 border-border/80 backdrop-blur-sm shadow-xs">
          <CardHeader className="pb-2 flex flex-row items-center justify-between space-y-0">
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              Job Status
            </span>
            <Activity className="w-4 h-4 text-amber-500" />
          </CardHeader>
          <CardContent>
            <div className="flex items-center gap-2">
              {statusData && statusData.active_jobs_count > 0 ? (
                <>
                  <span className="relative flex h-3 w-3">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
                  </span>
                  <span className="text-sm font-semibold text-emerald-500">Running Task</span>
                </>
              ) : (
                <>
                  <span className="inline-block w-2.5 h-2.5 rounded-full bg-muted-foreground/40"></span>
                  <span className="text-sm font-medium text-muted-foreground">Idle / Ready</span>
                </>
              )}
            </div>
            <p className="text-[11px] text-muted-foreground mt-2 truncate">
              {statusData && statusData.active_jobs_count > 0 && statusData.active_jobs[0]
                ? `${statusData.active_jobs[0].state || "USA"} • ${statusData.active_jobs[0].field || "All"}`
                : "ACID Checkpoints Enabled (SQLite WAL)"}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* ── Main Tabbed Workspaces ─────────────────────────────────────────── */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList className="bg-muted/70 p-1 border border-border/70 rounded-lg">
          <TabsTrigger value="states" className="gap-2 text-xs">
            <MapPin className="w-3.5 h-3.5" />
            States Coverage (50)
          </TabsTrigger>
          <TabsTrigger value="taxonomy" className="gap-2 text-xs">
            <Layers className="w-3.5 h-3.5" />
            Taxonomy & Overpass QL (13)
          </TabsTrigger>
          <TabsTrigger value="mirrors" className="gap-2 text-xs">
            <Server className="w-3.5 h-3.5" />
            Mirror Pool & Circuit Breaker
          </TabsTrigger>
          <TabsTrigger value="ingest" className="gap-2 text-xs">
            <Database className="w-3.5 h-3.5" />
            DB Ingestion & Exports
          </TabsTrigger>
          <TabsTrigger value="settings" className="gap-2 text-xs">
            <Sliders className="w-3.5 h-3.5" />
            Engine Settings
          </TabsTrigger>
        </TabsList>

        {/* ── TAB 1: States Coverage ────────────────────────────────────────── */}
        <TabsContent value="states" className="space-y-4">
          <Card className="border-border/80">
            <CardHeader className="pb-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <CardTitle className="text-base font-semibold">50 US States Geographic Bounding Matrix</CardTitle>
                <CardDescription className="text-xs">
                  Spatial bounding coordinates with chunk breakdown and completion tracking.
                </CardDescription>
              </div>

              <div className="flex items-center gap-2">
                <div className="relative w-48 sm:w-60">
                  <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    placeholder="Search state or code..."
                    value={stateSearch}
                    onChange={(e) => setStateSearch(e.target.value)}
                    className="pl-8 text-xs h-8"
                  />
                </div>

                <Select value={stateStatusFilter} onValueChange={(v: "all" | "completed" | "pending") => setStateStatusFilter(v)}>
                  <SelectTrigger className="text-xs h-8 w-28">
                    <SelectValue placeholder="Status" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all" className="text-xs">All States</SelectItem>
                    <SelectItem value="completed" className="text-xs">Completed</SelectItem>
                    <SelectItem value="pending" className="text-xs">Pending</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </CardHeader>

            <CardContent>
              <div className="rounded-md border border-border overflow-hidden">
                <div className="max-h-[560px] overflow-y-auto">
                  <table className="w-full text-xs text-left">
                    <thead className="bg-muted/50 text-muted-foreground sticky top-0 uppercase tracking-wider text-[10px] border-b border-border">
                      <tr>
                        <th className="py-2.5 px-4 font-semibold">State</th>
                        <th className="py-2.5 px-4 font-semibold">Code</th>
                        <th className="py-2.5 px-4 font-semibold">Bounding Box (S, W, N, E)</th>
                        <th className="py-2.5 px-4 font-semibold">Est. Chunks (0.5°)</th>
                        <th className="py-2.5 px-4 font-semibold">Status</th>
                        <th className="py-2.5 px-4 font-semibold text-right">Quick Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {filteredStates.map((st) => (
                        <tr key={st.name} className="hover:bg-muted/30 transition-colors">
                          <td className="py-2.5 px-4 font-medium text-foreground flex items-center gap-2">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                            {st.name}
                          </td>
                          <td className="py-2.5 px-4 font-mono font-medium">{st.code}</td>
                          <td className="py-2.5 px-4 font-mono text-muted-foreground text-[11px]">
                            [{st.bbox.min_lat}, {st.bbox.min_lon}, {st.bbox.max_lat}, {st.bbox.max_lon}]
                          </td>
                          <td className="py-2.5 px-4 font-mono">{st.estimated_chunks} chunks</td>
                          <td className="py-2.5 px-4">
                            {st.is_completed ? (
                              <Badge className="bg-emerald-500/10 text-emerald-500 border-emerald-500/20 text-[10px]">
                                Completed
                              </Badge>
                            ) : (
                              <Badge variant="outline" className="text-muted-foreground text-[10px]">
                                Ready
                              </Badge>
                            )}
                          </td>
                          <td className="py-2.5 px-4 text-right">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 text-xs gap-1 hover:text-emerald-500"
                              onClick={() => {
                                setSelectedStateForRun(st.name);
                                setIngestState(st.name);
                                setActiveTab("ingest");
                              }}
                            >
                              Actions
                              <ChevronRight className="w-3 h-3" />
                            </Button>
                          </td>
                        </tr>
                      ))}
                      {filteredStates.length === 0 && (
                        <tr>
                          <td colSpan={6} className="py-8 text-center text-muted-foreground text-xs">
                            No states match the specified query.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── TAB 2: Taxonomy & Query Templates ─────────────────────────────── */}
        <TabsContent value="taxonomy" className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Left Column: Category List */}
            <Card className="border-border/80 md:col-span-1">
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-semibold">13 Business Categories</CardTitle>
                <CardDescription className="text-xs">
                  Unified POI schema mapped to OneExtraction company models.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-1.5 p-3">
                {fieldsList.map((f) => {
                  const isSelected = selectedFieldForPreview?.field === f.field;
                  return (
                    <button
                      key={f.field}
                      onClick={() => setSelectedFieldForPreview(f)}
                      className={`w-full text-left px-3 py-2.5 rounded-md text-xs flex items-center justify-between transition-all ${
                        isSelected
                          ? "bg-primary text-primary-foreground font-medium shadow-xs"
                          : "hover:bg-muted/60 text-foreground"
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${isSelected ? "bg-white" : "bg-emerald-500"}`}></span>
                        <span className="capitalize">{f.field}</span>
                      </div>
                      <Badge
                        variant="outline"
                        className={`text-[10px] ${
                          isSelected ? "border-white/30 text-white" : "text-muted-foreground"
                        }`}
                      >
                        {f.category_group}
                      </Badge>
                    </button>
                  );
                })}
              </CardContent>
            </Card>

            {/* Right Column: Query Template & Overpass QL Preview */}
            <Card className="border-border/80 md:col-span-2">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <div>
                    <CardTitle className="text-base font-semibold capitalize flex items-center gap-2">
                      <Code2 className="w-4 h-4 text-emerald-500" />
                      {selectedFieldForPreview?.field || "Category"} Query Template
                    </CardTitle>
                    <CardDescription className="text-xs mt-0.5">
                      {selectedFieldForPreview?.description}
                    </CardDescription>
                  </div>
                  <Badge variant="outline" className="text-xs">
                    Category: {selectedFieldForPreview?.category_group}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    Overpass QL Code Block
                  </Label>
                  <pre className="p-4 rounded-md bg-zinc-950 text-zinc-100 text-xs font-mono overflow-x-auto border border-zinc-800 leading-relaxed">
                    <code>
                      {`[out:json][timeout:35];\n(\n  ${selectedFieldForPreview?.query_template || ""}\n);\nout body qt;\n>;\nout skel qt;`}
                    </code>
                  </pre>
                </div>

                <div className="p-3.5 rounded-lg bg-muted/40 border border-border text-xs space-y-1.5">
                  <span className="font-semibold text-foreground flex items-center gap-1.5">
                    <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
                    Extraction Assurance:
                  </span>
                  <p className="text-muted-foreground text-[11px] leading-normal">
                    Queries are executed chunk-by-chunk using adaptive spatial bounding boxes. If the Overpass server encounters HTTP 504 timeouts or heavy loads, the quadtree engine automatically bisects the chunk into 4 sub-quadrants and aggregates all returned POIs deterministically.
                  </p>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ── TAB 3: Mirror Pool & Circuit Breaker ───────────────────────────── */}
        <TabsContent value="mirrors" className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-base font-semibold">Global Overpass Mirror Network</h3>
              <p className="text-xs text-muted-foreground">
                Automatic failover, jittered exponential backoff, and circuit breaker isolation.
              </p>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={handleProbeMirrors}
              disabled={isProbingMirrors}
              className="gap-2 text-xs"
            >
              <Zap className={`w-3.5 h-3.5 text-amber-500 ${isProbingMirrors ? "animate-pulse" : ""}`} />
              {isProbingMirrors ? "Probing Mirrors..." : "Probe All Mirrors"}
            </Button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {mirrorsData?.mirrors.map((mirror) => (
              <Card key={mirror.url} className="border-border/80">
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span
                          className={`w-2.5 h-2.5 rounded-full ${
                            mirror.is_healthy ? "bg-emerald-500" : "bg-red-500"
                          }`}
                        />
                        <CardTitle className="text-sm font-semibold truncate max-w-[280px]">
                          {new URL(mirror.url).hostname}
                        </CardTitle>
                      </div>
                      <CardDescription className="text-[11px] font-mono truncate">
                        {mirror.url}
                      </CardDescription>
                    </div>

                    <div className="flex flex-col items-end gap-1">
                      {mirror.is_active && (
                        <Badge className="bg-blue-500/10 text-blue-500 border-blue-500/20 text-[10px]">
                          Active Mirror
                        </Badge>
                      )}
                      <Badge
                        variant="outline"
                        className={`text-[10px] ${
                          mirror.is_healthy
                            ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/30"
                            : "bg-red-500/10 text-red-500 border-red-500/30"
                        }`}
                      >
                        {mirror.is_healthy ? "Healthy" : "In Cooldown"}
                      </Badge>
                    </div>
                  </div>
                </CardHeader>

                <CardContent className="space-y-3 pt-2 text-xs">
                  <div className="grid grid-cols-3 gap-2 py-2 px-3 rounded-md bg-muted/40 font-mono text-[11px]">
                    <div>
                      <div className="text-muted-foreground text-[10px]">Successes</div>
                      <div className="font-semibold text-emerald-500">{mirror.total_successes}</div>
                    </div>
                    <div>
                      <div className="text-muted-foreground text-[10px]">Failures</div>
                      <div className="font-semibold text-red-500">{mirror.total_failures}</div>
                    </div>
                    <div>
                      <div className="text-muted-foreground text-[10px]">Latency</div>
                      <div className="font-semibold text-foreground">
                        {mirror.latency_ms ? `${mirror.latency_ms} ms` : "—"}
                      </div>
                    </div>
                  </div>

                  {!mirror.is_healthy && (
                    <div className="p-2.5 rounded bg-red-500/10 border border-red-500/20 text-red-600 text-[11px] space-y-1">
                      <div className="font-medium flex items-center gap-1.5">
                        <AlertTriangle className="w-3.5 h-3.5" />
                        Circuit Tripped: Isolated for {mirror.cooldown_remaining_sec}s
                      </div>
                      <div className="text-[10px] text-red-500 truncate">
                        Error: {mirror.last_error_message || "Server timeout (HTTP 504)"}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>

        {/* ── TAB 4: DB Ingestion & Export Downloads ─────────────────────────── */}
        <TabsContent value="ingest" className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Card 1: Batch Deduplicated Ingestion */}
            <Card className="border-border/80">
              <CardHeader>
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Database className="w-4 h-4 text-emerald-500" />
                  Canonical Database Ingestion
                </CardTitle>
                <CardDescription className="text-xs">
                  Loads extracted OSM datasets, normalizes fields, and deduplicates against existing records via OneExtraction Deduplicator.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label className="text-xs">Select State</Label>
                    <Select value={ingestState} onValueChange={setIngestState}>
                      <SelectTrigger className="text-xs">
                        <SelectValue placeholder="State" />
                      </SelectTrigger>
                      <SelectContent className="max-h-52">
                        {statesList.map((s) => (
                          <SelectItem key={s.name} value={s.name} className="text-xs">
                            {s.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1.5">
                    <Label className="text-xs">Select Field</Label>
                    <Select value={ingestField} onValueChange={setIngestField}>
                      <SelectTrigger className="text-xs">
                        <SelectValue placeholder="Field" />
                      </SelectTrigger>
                      <SelectContent className="max-h-52">
                        {fieldsList.map((f) => (
                          <SelectItem key={f.field} value={f.field} className="text-xs">
                            {f.field.toUpperCase()}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="flex items-center gap-2 pt-1">
                  <label className="flex items-center gap-2 text-xs cursor-pointer">
                    <input
                      type="checkbox"
                      checked={ingestDryRun}
                      onChange={(e) => setIngestDryRun(e.target.checked)}
                      className="rounded border-border"
                    />
                    Dry Run Mode (Validate schema & scoring without writing to DB)
                  </label>
                </div>

                <Button
                  onClick={handleIngest}
                  disabled={isIngesting}
                  className="w-full text-xs bg-emerald-600 hover:bg-emerald-700 text-white gap-2"
                >
                  <Database className="w-3.5 h-3.5" />
                  {isIngesting ? "Processing Ingestion..." : "Execute Deduplicated Ingestion"}
                </Button>
              </CardContent>
            </Card>

            {/* Card 2: Export & Reconcile */}
            <Card className="border-border/80">
              <CardHeader>
                <CardTitle className="text-base font-semibold flex items-center gap-2">
                  <Download className="w-4 h-4 text-blue-500" />
                  Data Export & Checkpoint Reconciliation
                </CardTitle>
                <CardDescription className="text-xs">
                  Download clean exported datasets in JSON or CSV, or audit SQLite WAL state against disk.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="p-3.5 rounded-lg bg-muted/40 border border-border space-y-2">
                  <div className="text-xs font-semibold text-foreground">
                    Export {ingestState} • {ingestField}
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleDownload(ingestState, ingestField, "json")}
                      className="flex-1 text-xs gap-1.5"
                    >
                      <Code2 className="w-3.5 h-3.5 text-blue-500" />
                      JSON Dataset
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleDownload(ingestState, ingestField, "csv")}
                      className="flex-1 text-xs gap-1.5"
                    >
                      <FileSpreadsheet className="w-3.5 h-3.5 text-emerald-500" />
                      CSV Spreadsheet
                    </Button>
                  </div>
                </div>

                <Separator />

                <div className="space-y-2">
                  <div className="text-xs font-semibold text-foreground flex items-center justify-between">
                    <span>ACID Checkpoint Auditor</span>
                    <Badge variant="outline" className="text-[10px]">WAL Mode</Badge>
                  </div>
                  <p className="text-[11px] text-muted-foreground">
                    Verifies processed chunks on disk against the SQLite checkpoint database and reconciles any orphan states.
                  </p>
                  <Button
                    variant="outline"
                    onClick={handleReconcile}
                    disabled={isReconciling}
                    className="w-full text-xs gap-2"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${isReconciling ? "animate-spin" : ""}`} />
                    {isReconciling ? "Reconciling Checkpoints..." : "Reconcile Disk & DB Checkpoints"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ── TAB 5: Engine Configuration ──────────────────────────────────── */}
        <TabsContent value="settings" className="space-y-4">
          <Card className="border-border/80">
            <CardHeader>
              <CardTitle className="text-base font-semibold flex items-center gap-2">
                <Sliders className="w-4 h-4 text-emerald-500" />
                Overpass Network & Resilience Settings
              </CardTitle>
              <CardDescription className="text-xs">
                Fine-tune quadtree recursion limits, timeouts, and rate limits in real-time.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {configData ? (
                <form onSubmit={handleSaveConfig} className="space-y-4">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                      <Label className="text-xs">Connect Timeout (seconds)</Label>
                      <Input
                        name="connect_timeout_sec"
                        type="number"
                        min="1"
                        max="60"
                        defaultValue={configData.connect_timeout_sec}
                        className="text-xs font-mono"
                      />
                    </div>

                    <div className="space-y-1.5">
                      <Label className="text-xs">Read / Query Timeout (seconds)</Label>
                      <Input
                        name="read_timeout_sec"
                        type="number"
                        min="5"
                        max="300"
                        defaultValue={configData.read_timeout_sec}
                        className="text-xs font-mono"
                      />
                    </div>

                    <div className="space-y-1.5">
                      <Label className="text-xs">Circuit Breaker Cooldown (seconds)</Label>
                      <Input
                        name="circuit_breaker_cooldown_sec"
                        type="number"
                        step="10"
                        defaultValue={configData.circuit_breaker_cooldown_sec}
                        className="text-xs font-mono"
                      />
                    </div>

                    <div className="space-y-1.5">
                      <Label className="text-xs">Max Quadtree Bisection Depth</Label>
                      <Input
                        name="max_quadtree_depth"
                        type="number"
                        min="1"
                        max="6"
                        defaultValue={configData.max_quadtree_depth}
                        className="text-xs font-mono"
                      />
                    </div>

                    <div className="space-y-1.5">
                      <Label className="text-xs">Default Chunk Size (degrees)</Label>
                      <Input
                        name="chunk_size_deg"
                        type="number"
                        step="0.05"
                        defaultValue={configData.chunk_size_deg}
                        className="text-xs font-mono"
                      />
                    </div>

                    <div className="space-y-1.5">
                      <Label className="text-xs">Rate Limit Delay (seconds)</Label>
                      <Input
                        name="rate_limit_delay_sec"
                        type="number"
                        step="0.1"
                        defaultValue={configData.rate_limit_delay_sec}
                        className="text-xs font-mono"
                      />
                    </div>
                  </div>

                  <div className="space-y-1.5 pt-2">
                    <Label className="text-xs">Contact Email (for User-Agent compliance)</Label>
                    <Input
                      name="contact_email"
                      type="email"
                      defaultValue={configData.contact_email}
                      className="text-xs font-mono"
                    />
                  </div>

                  <div className="pt-2 flex justify-end">
                    <Button
                      type="submit"
                      disabled={isSavingConfig}
                      className="text-xs bg-emerald-600 hover:bg-emerald-700 text-white gap-2"
                    >
                      <Check className="w-3.5 h-3.5" />
                      {isSavingConfig ? "Saving..." : "Save Configuration"}
                    </Button>
                  </div>
                </form>
              ) : (
                <div className="py-8 text-center text-xs text-muted-foreground">
                  Loading configuration...
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
